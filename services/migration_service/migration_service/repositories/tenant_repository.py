# LOCATION: services/migration_service/migration_service/repositories/tenant_repository.py

"""
Repository layer for the `tenants` table.

Repository pattern per Section 6: this is the ONLY place that issues
queries against `tenants`. Services call these methods; they never
build SQLAlchemy queries themselves.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Tenant


class TenantNotFoundError(Exception):
    def __init__(self, tenant_id: uuid.UUID):
        super().__init__(f"Tenant {tenant_id} not found")
        self.tenant_id = tenant_id


class TenantRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(select(Tenant).where(Tenant.tenant_id == tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise TenantNotFoundError(tenant_id)
        return tenant

    async def get_by_domain(self, company_domain: str) -> Tenant | None:
        result = await self._session.execute(
            select(Tenant).where(Tenant.company_domain == company_domain)
        )
        return result.scalar_one_or_none()

    async def create_pending(
        self,
        *,
        tenant_id: uuid.UUID,
        subdomain: str,
        company_name: str,
        company_domain: str,
        created_by_user_id: uuid.UUID,
        plan: str = "trial",
    ) -> Tenant:
        """Create a tenant row with status=PENDING. Called by the Auth
        Service at signup time (Task C), before the Migration Service
        has provisioned the tenant DB."""
        tenant = Tenant(
            tenant_id=tenant_id,
            subdomain=subdomain,
            company_name=company_name,
            company_domain=company_domain,
            created_by_user_id=created_by_user_id,
            plan=plan,
            status="PENDING",
        )
        self._session.add(tenant)
        await self._session.flush()
        return tenant

    async def set_connection_string_and_activate(
        self, tenant_id: uuid.UUID, encrypted_connection_string: str
    ) -> Tenant:
        """Called once the Migration Service has provisioned the tenant
        DB and run its migration suite: stores the (already-encrypted)
        connection string and flips status to ACTIVE."""
        tenant = await self.get_by_id(tenant_id)
        tenant.db_connection_string = encrypted_connection_string
        tenant.status = "ACTIVE"
        await self._session.flush()
        return tenant

    async def mark_failed(self, tenant_id: uuid.UUID) -> Tenant:
        """Called when provisioning fails — tenant stays visible in the
        control plane for support/debugging rather than being deleted."""
        tenant = await self.get_by_id(tenant_id)
        tenant.status = "FAILED"
        await self._session.flush()
        return tenant

    async def suspend(self, tenant_id: uuid.UUID, reason: str) -> Tenant:
        tenant = await self.get_by_id(tenant_id)
        tenant.status = "SUSPENDED"
        tenant.suspended_reason = reason
        tenant.suspended_at = datetime.now(timezone.utc)
        await self._session.flush()
        return tenant

    async def list_active(self) -> list[Tenant]:
        """Used by the system-admin-triggered 'run migrations across all
        tenants' command (Section 3, Migration Service)."""
        result = await self._session.execute(select(Tenant).where(Tenant.status == "ACTIVE"))
        return list(result.scalars().all())
