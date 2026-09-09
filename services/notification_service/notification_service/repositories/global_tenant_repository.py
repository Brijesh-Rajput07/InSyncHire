# LOCATION: services/notification_service/notification_service/repositories/global_tenant_repository.py

"""Read-only repository for `tenants` (insynchire_global) -- used to
personalize emails with the tenant's display name and, via
`TenantResolver`, to resolve/decrypt a tenant's connection string.
Notification Service never writes this table."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from ..models import Tenant


class TenantNotFoundError(Exception):
    def __init__(self, tenant_id: uuid.UUID):
        super().__init__(f"Tenant {tenant_id} not found")


class GlobalTenantRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def get_by_id(self, tenant_id: uuid.UUID) -> Tenant:
        async with self._session_factory() as session:
            result = await session.execute(select(Tenant).where(Tenant.tenant_id == tenant_id))
            tenant = result.scalar_one_or_none()
            if tenant is None:
                raise TenantNotFoundError(tenant_id)
            return tenant