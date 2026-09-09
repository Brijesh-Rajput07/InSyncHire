# LOCATION: services/notification_service/notification_service/repositories/membership_repository.py

"""Read-only repository for `tenant_user_memberships` (tenant DB) --
used ONLY to find which `user_id`s hold `company_admin`/`recruiter`
roles in a tenant, so `application.submitted`/`scorecard.generated`
notifications reach the hiring team. Never writes this table --
Tenant Service owns it."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TenantUserMembership


class MembershipRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_user_ids_for_roles(self, tenant_id: uuid.UUID, roles: list[str]) -> list[uuid.UUID]:
        result = await self._session.execute(
            select(TenantUserMembership.user_id).where(
                TenantUserMembership.tenant_id == tenant_id, TenantUserMembership.role.in_(roles)
            )
        )
        return [row[0] for row in result.all()]