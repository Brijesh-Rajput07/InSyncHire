# LOCATION: services/notification_service/notification_service/repositories/job_opening_repository.py

"""Read-only repository for `job_openings` (tenant DB) -- resolves
`job_id` -> title so recruiter/candidate emails can name the role.
Never writes this table -- Job Service owns it."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import JobOpening


class JobOpeningRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_title(self, job_id: uuid.UUID) -> str | None:
        result = await self._session.execute(select(JobOpening.title).where(JobOpening.job_id == job_id))
        row = result.first()
        return row[0] if row else None