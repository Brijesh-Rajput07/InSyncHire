# LOCATION: services/tenant_service/tenant_service/repositories/invite_repository.py

"""Repository for `invited_users` (tenant DB)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import InvitedUser


class InviteRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> InvitedUser | None:
        result = await self._session.execute(
            select(InvitedUser).where(InvitedUser.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def get_pending_by_email(self, tenant_id: uuid.UUID, email: str) -> InvitedUser | None:
        result = await self._session.execute(
            select(InvitedUser).where(
                InvitedUser.tenant_id == tenant_id,
                InvitedUser.email == email,
                InvitedUser.is_accepted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        email: str,
        role: str,
        invited_by: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> InvitedUser:
        invite = InvitedUser(
            invite_id=uuid.uuid4(),
            tenant_id=tenant_id,
            email=email,
            role=role,
            invited_by=invited_by,
            token_hash=token_hash,
            expires_at=expires_at,
            is_accepted=False,
        )
        self._session.add(invite)
        await self._session.flush()
        return invite

    async def mark_accepted(self, invite: InvitedUser) -> InvitedUser:
        invite.is_accepted = True
        invite.accepted_at = datetime.now(timezone.utc)
        await self._session.flush()
        return invite