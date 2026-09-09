# LOCATION: services/job_service/job_service/repositories/job_opening_repository.py

"""Repository for `job_openings` (tenant DB)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import JobOpening


class JobOpeningRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, job_id: uuid.UUID) -> JobOpening | None:
        result = await self._session.execute(select(JobOpening).where(JobOpening.job_id == job_id))
        return result.scalar_one_or_none()

    async def list_for_org(self, org_id: uuid.UUID) -> list[JobOpening]:
        result = await self._session.execute(
            select(JobOpening).where(JobOpening.org_id == org_id).order_by(JobOpening.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_open(self) -> list[JobOpening]:
        """Every OPEN posting in this tenant DB -- used by the interim
        public board's per-tenant scan (see public_board_service.py)."""
        result = await self._session.execute(
            select(JobOpening).where(JobOpening.status == "OPEN").order_by(JobOpening.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        org_id: uuid.UUID,
        title: str,
        description: str,
        requirements: str | None,
        skills_tags: list[str],
        experience_level: str | None,
        location: str | None,
        salary_min: int | None,
        salary_max: int | None,
        posted_by: uuid.UUID,
    ) -> JobOpening:
        job = JobOpening(
            job_id=uuid.uuid4(), tenant_id=tenant_id, org_id=org_id, title=title, description=description,
            requirements=requirements, skills_tags=skills_tags, experience_level=experience_level,
            location=location, salary_min=salary_min, salary_max=salary_max, posted_by=posted_by, status="OPEN",
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def update(self, job: JobOpening, update_data: dict) -> JobOpening:
        for field, value in update_data.items():
            setattr(job, field, value)
        await self._session.flush()
        return job

    async def close(self, job: JobOpening) -> JobOpening:
        from datetime import datetime, timezone

        job.status = "CLOSED"
        job.closed_at = datetime.now(timezone.utc)
        await self._session.flush()
        return job

    async def increment_application_count(self, job: JobOpening) -> JobOpening:
        job.application_count += 1
        await self._session.flush()
        return job