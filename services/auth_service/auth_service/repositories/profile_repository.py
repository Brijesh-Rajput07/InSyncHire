# LOCATION: services/auth_service/auth_service/repositories/profile_repository.py

"""Repository for `user_profiles` (users_db).

FIX-M2 UPDATE: no longer instantiated anywhere in this service's actual
runtime wiring (dependencies.py has no users_db engine anymore) --
kept as a reference implementation for M4's dedicated service, which
will be the one place that actually creates this row, triggered by
consuming `user.registered` rather than a direct write from signup."""

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

    async def create_blank_profile(self, user_id: uuid.UUID) -> UserProfile:
        """Called once, right after candidate signup completes. Full
        profile editing (bio, skills, links, etc.) is out of scope for
        Auth Service — that's M4's candidate profile management."""
        existing = await self.get_by_user_id(user_id)
        if existing is not None:
            return existing
        profile = UserProfile(user_id=user_id)
        self._session.add(profile)
        await self._session.flush()
        return profile
