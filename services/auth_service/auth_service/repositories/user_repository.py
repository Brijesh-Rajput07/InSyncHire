# LOCATION: services/auth_service/auth_service/repositories/user_repository.py

"""Repository for `global_users` (insynchire_global)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import GlobalUser


class EmailAlreadyRegisteredError(Exception):
    def __init__(self, email: str):
        super().__init__(f"Email '{email}' is already registered")
        self.email = email


class UserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_email(self, email: str) -> GlobalUser | None:
        result = await self._session.execute(select(GlobalUser).where(GlobalUser.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> GlobalUser | None:
        result = await self._session.execute(select(GlobalUser).where(GlobalUser.user_id == user_id))
        return result.scalar_one_or_none()

    async def create_user(
        self,
        *,
        user_id: uuid.UUID,
        email: str,
        password_hash: str,
        full_name: str,
        account_type: str,
        is_email_verified: bool = False,
    ) -> GlobalUser:
        if await self.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError(email)

        user = GlobalUser(
            user_id=user_id,
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            account_type=account_type,
            is_email_verified=is_email_verified,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def mark_email_verified(self, user_id: uuid.UUID) -> GlobalUser:
        user = await self.get_by_id(user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        user.is_email_verified = True
        await self._session.flush()
        return user

    async def record_login(self, user_id: uuid.UUID) -> None:
        user = await self.get_by_id(user_id)
        if user is not None:
            user.last_login_at = datetime.now(timezone.utc)
            await self._session.flush()
