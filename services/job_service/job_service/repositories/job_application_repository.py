# LOCATION: services/job_service/job_service/repositories/job_application_repository.py

"""Repository for `job_applications` (tenant DB)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import JobApplication


class JobApplicationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, application_id: uuid.UUID) -> JobApplication | None:
        result = await self._session.execute(
            select(JobApplication).where(JobApplication.application_id == application_id)
        )
        return result.scalar_one_or_none()

    async def get_by_job_and_candidate(
        self, job_id: uuid.UUID, candidate_user_id: uuid.UUID
    ) -> JobApplication | None:
        result = await self._session.execute(
            select(JobApplication).where(
                JobApplication.job_id == job_id, JobApplication.candidate_user_id == candidate_user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_for_job(self, job_id: uuid.UUID) -> list[JobApplication]:
        result = await self._session.execute(
            select(JobApplication).where(JobApplication.job_id == job_id).order_by(JobApplication.applied_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        candidate_user_id: uuid.UUID,
        resume_id: uuid.UUID | None,
        cover_note: str | None,
    ) -> JobApplication:
        application = JobApplication(
            application_id=uuid.uuid4(), tenant_id=tenant_id, job_id=job_id,
            candidate_user_id=candidate_user_id, resume_id=resume_id, cover_note=cover_note, status="APPLIED",
        )
        self._session.add(application)
        await self._session.flush()
        return application

    async def set_status(
        self, application: JobApplication, *, status: str, reviewed_by: uuid.UUID
    ) -> JobApplication:
        application.status = status
        application.reviewed_by = reviewed_by
        application.reviewed_at = datetime.now(timezone.utc)
        await self._session.flush()
        return application