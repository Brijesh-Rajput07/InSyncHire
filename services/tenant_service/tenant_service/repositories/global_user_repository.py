# LOCATION: services/tenant_service/tenant_service/repositories/global_user_repository.py

"""
Read-only repository for `global_users` (insynchire_global).

FIX-M3: exists specifically to support the "existing user" invite
confirmation flow — checking whether the person accepting an invite
already has a `candidate` account, so we can require an explicit
confirmation before that identity also gains company-side access (see
invite_acceptance_service.py). Tenant Service never writes this table
-- see models/global_models.py.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
