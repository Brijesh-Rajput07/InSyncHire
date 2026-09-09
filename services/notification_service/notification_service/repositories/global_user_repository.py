# LOCATION: services/notification_service/notification_service/repositories/global_user_repository.py

"""Read-only repository for `global_users` (insynchire_global) --
resolves a `user_id` (or a batch of them) to an email address so
Notification Service knows where to send. Never writes this table."""

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

    async def get_by_id(self, user_id: uuid.UUID) -> GlobalUser:
        async with self._session_factory() as session:
            result = await session.execute(select(GlobalUser).where(GlobalUser.user_id == user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise GlobalUserNotFoundError(user_id)
            return user

    async def get_email(self, user_id: uuid.UUID) -> str:
        user = await self.get_by_id(user_id)
        return user.email

    async def get_emails(self, user_ids: list[uuid.UUID]) -> list[str]:
        """Batch lookup -- skips any user_id that doesn't resolve
        (logged by the caller) rather than failing the whole batch,
        since one bad/stale user_id shouldn't block notifying everyone
        else."""
        if not user_ids:
            return []
        async with self._session_factory() as session:
            result = await session.execute(select(GlobalUser).where(GlobalUser.user_id.in_(user_ids)))
            return [user.email for user in result.scalars().all()]