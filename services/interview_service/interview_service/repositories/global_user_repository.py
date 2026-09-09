# LOCATION: services/interview_service/interview_service/repositories/global_user_repository.py

"""Read-only repository for `global_users` (insynchire_global) -- same
account_type check `job_service`/`user_profile_service` use to tell a
candidate apart from an unselected company_user, since candidate tokens
are always issued with role=None (see auth_dependency.py's docstring)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from ..models import GlobalUser


class GlobalUserNotFoundError(Exception):
    def __init__(self, user_id: uuid.UUID):
        super().__init__(f"Global user {user_id} not found")


class GlobalUserRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def get_account_type(self, user_id: uuid.UUID) -> str:
        async with self._session_factory() as session:
            result = await session.execute(select(GlobalUser).where(GlobalUser.user_id == user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise GlobalUserNotFoundError(user_id)
            return user.account_type