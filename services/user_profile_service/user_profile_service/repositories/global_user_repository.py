# LOCATION: services/user_profile_service/user_profile_service/repositories/global_user_repository.py

"""Read-only repository for `global_users` (insynchire_global) -- see
models/global_models.py's docstring for why this service needs it at
all (candidate tokens carry role=None, so account_type is the only way
to tell a candidate apart from an unselected company_user). This
service never writes global_users."""

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