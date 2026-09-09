# LOCATION: services/job_service/job_service/services/job_posting_service.py

"""
Job posting CRUD business logic (Section: STAGE 1 — JOB POSTING).
Every method takes an already-resolved tenant-scoped session (opened by
the route layer via TenantResolver against the caller's OWN tenant_id
from their verified token) -- there is no method here that takes a
tenant_id as a parameter to switch into, by design, matching the same
discipline used everywhere else in this codebase (Tenant Service's
services never take an arbitrary tenant_id either).
"""

from __future__ import annotations

import uuid

from insynchire_events import Topics
from insynchire_events.schemas import JobPostedEvent
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import JobOpening
from ..repositories import JobOpeningRepository


class JobPostingError(Exception):
    """Base class for job posting failures."""


class JobNotFoundError(JobPostingError):
    def __init__(self, job_id: uuid.UUID):
        super().__init__(f"Job {job_id} not found")


class JobNotInThisOrgError(JobPostingError):
    def __init__(self):
        super().__init__("This job does not belong to your organization")


class JobPostingService:
    def __init__(self, *, publish):
        self._publish = publish

    async def create_job(
        self,
        *,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        org_id: uuid.UUID,
        posted_by: uuid.UUID,
        create_data: dict,
        trace_id: str,
    ) -> JobOpening:
        job = await JobOpeningRepository(session).create(
            tenant_id=tenant_id, org_id=org_id, posted_by=posted_by, **create_data
        )
        await session.commit()
        await session.refresh(job)

        await self._publish(
            Topics.JOB_POSTED.value,
            JobPostedEvent(
                trace_id=trace_id, tenant_id=tenant_id, job_id=job.job_id, org_id=org_id, title=job.title,
                posted_by=posted_by,
            ),
        )
        return job

    async def _get_owned_job(self, session: AsyncSession, *, job_id: uuid.UUID, org_id: uuid.UUID) -> JobOpening:
        job = await JobOpeningRepository(session).get_by_id(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        if job.org_id != org_id:
            raise JobNotInThisOrgError()
        return job

    async def get_job(self, session: AsyncSession, *, job_id: uuid.UUID, org_id: uuid.UUID) -> JobOpening:
        return await self._get_owned_job(session, job_id=job_id, org_id=org_id)

    async def list_jobs(self, session: AsyncSession, *, org_id: uuid.UUID) -> list[JobOpening]:
        return await JobOpeningRepository(session).list_for_org(org_id)

    async def update_job(
        self, session: AsyncSession, *, job_id: uuid.UUID, org_id: uuid.UUID, update_data: dict
    ) -> JobOpening:
        job = await self._get_owned_job(session, job_id=job_id, org_id=org_id)
        job = await JobOpeningRepository(session).update(job, update_data)
        await session.commit()
        await session.refresh(job)
        return job

    async def close_job(self, session: AsyncSession, *, job_id: uuid.UUID, org_id: uuid.UUID) -> JobOpening:
        """Section 5 / job_openings.status -- closing a job is a soft
        delete (status=CLOSED, closed_at set), never a hard delete: the
        row (and every application against it) must survive for the
        audit trail (Section 8)."""
        job = await self._get_owned_job(session, job_id=job_id, org_id=org_id)
        job = await JobOpeningRepository(session).close(job)
        await session.commit()
        await session.refresh(job)
        return job