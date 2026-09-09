# LOCATION: services/tenant_service/tenant_service/repositories/membership_repository.py

"""Repository for `tenant_user_memberships` (tenant DB)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TenantUserMembership


class MembershipAlreadyExistsError(Exception):
    def __init__(self, user_id: uuid.UUID, tenant_id: uuid.UUID):
        super().__init__(f"User {user_id} already has a membership in tenant {tenant_id}")


class MembershipRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_user_and_tenant(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> TenantUserMembership | None:
        result = await self._session.execute(
            select(TenantUserMembership).where(
                TenantUserMembership.user_id == user_id,
                TenantUserMembership.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        org_id: uuid.UUID,
        role: str,
        invited_by: uuid.UUID | None = None,
    ) -> TenantUserMembership:
        existing = await self.get_by_user_and_tenant(user_id, tenant_id)
        if existing is not None:
            raise MembershipAlreadyExistsError(user_id, tenant_id)

        membership = TenantUserMembership(
            membership_id=uuid.uuid4(),
            user_id=user_id,
            tenant_id=tenant_id,
            org_id=org_id,
            role=role,
            invited_by=invited_by,
            is_active=True,
        )
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> list[TenantUserMembership]:
        result = await self._session.execute(
            select(TenantUserMembership).where(TenantUserMembership.tenant_id == tenant_id)
        )
        return list(result.scalars().all())
