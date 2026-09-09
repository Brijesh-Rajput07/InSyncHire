# LOCATION: services/user_profile_service/user_profile_service/repositories/application_index_repository.py

"""Repository for `user_applications_index` (users_db) -- M5 addition.

This table was scaffolded in M4 (`models/users_db_models.py`'s
`UserApplicationIndex`, migration `0002_resumes_applications_notifications`)
with a docstring saying Job Service (M5) would populate it. Following
this codebase's established FIX-M2 precedent -- no service writes
another service's database directly, cross-service needs go through
Kafka -- Job Service does NOT write users_db itself. Instead, this
service (the one and only owner of users_db) gets a new consumer for
`application.submitted` (see
services/application_submitted_consumer_service.py) and this repository
is what that consumer uses to create/update the index row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import UserApplicationIndex


class ApplicationIndexRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_application_id(self, application_id: uuid.UUID) -> UserApplicationIndex | None:
        result = await self._session.execute(
            select(UserApplicationIndex).where(UserApplicationIndex.application_id == application_id)
        )
        return result.scalar_one_or_none()

    async def create_or_touch(
        self, *, application_id: uuid.UUID, user_id: uuid.UUID, tenant_id: uuid.UUID, job_id: uuid.UUID
    ) -> UserApplicationIndex:
        """Idempotent, same discipline as ProfileRepository.create_blank
        -- a redelivered `application.submitted` (Kafka at-least-once)
        must not raise or create a duplicate row; it just bumps
        `last_updated`."""
        existing = await self.get_by_application_id(application_id)
        if existing is not None:
            existing.last_updated = datetime.now(timezone.utc)
            await self._session.flush()
            return existing

        index_row = UserApplicationIndex(
            application_id=application_id, user_id=user_id, tenant_id=tenant_id, job_id=job_id,
            current_stage="applied",
        )
        self._session.add(index_row)
        await self._session.flush()
        return index_row