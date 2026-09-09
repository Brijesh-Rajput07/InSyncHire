# LOCATION: services/user_profile_service/user_profile_service/repositories/profile_repository.py

"""Repository for `user_profiles` (users_db) -- this service's owned table."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import UserProfile


class ProfileRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_user_id(self, user_id: uuid.UUID) -> UserProfile | None:
        result = await self._session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        return result.scalar_one_or_none()

    async def create_blank(self, user_id: uuid.UUID) -> UserProfile:
        """Idempotent: if a profile already exists for `user_id` (e.g. a
        redelivered `user.registered` Kafka message -- at-least-once
        semantics), returns the existing row rather than raising or
        creating a duplicate."""
        existing = await self.get_by_user_id(user_id)
        if existing is not None:
            return existing
        profile = UserProfile(user_id=user_id)
        self._session.add(profile)
        await self._session.flush()
        return profile