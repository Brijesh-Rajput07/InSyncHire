# LOCATION: services/tenant_service/tenant_service/repositories/organization_repository.py

"""Repository for `organizations` (tenant DB)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Organization


class OrganizationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_tenant_id(self, tenant_id: uuid.UUID) -> Organization | None:
        result = await self._session.execute(
            select(Organization).where(Organization.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def create(self, *, tenant_id: uuid.UUID, name: str) -> Organization:
        existing = await self.get_by_tenant_id(tenant_id)
        if existing is not None:
            return existing
        org = Organization(org_id=uuid.uuid4(), tenant_id=tenant_id, name=name, settings={})
        self._session.add(org)
        await self._session.flush()
        return org
