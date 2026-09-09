# LOCATION: services/auth_service/auth_service/repositories/tenant_repository.py

"""
Repository for `tenants` (insynchire_global) — Auth Service's slice.
Only what company signup needs: check domain uniqueness, create the
PENDING row. Activation/connection-string storage is Migration
Service's job (M1), not this service's.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Tenant


class DomainAlreadyRegisteredError(Exception):
    def __init__(self, domain: str):
        super().__init__(f"Domain '{domain}' is already registered to a tenant")
        self.domain = domain


class SubdomainTakenError(Exception):
    def __init__(self, subdomain: str):
        super().__init__(f"Subdomain '{subdomain}' is already taken")
        self.subdomain = subdomain


class TenantRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_domain(self, company_domain: str) -> Tenant | None:
        result = await self._session.execute(select(Tenant).where(Tenant.company_domain == company_domain))
        return result.scalar_one_or_none()

    async def get_by_subdomain(self, subdomain: str) -> Tenant | None:
        result = await self._session.execute(select(Tenant).where(Tenant.subdomain == subdomain))
        return result.scalar_one_or_none()

    async def create_pending(
        self,
        *,
        tenant_id: uuid.UUID,
        subdomain: str,
        company_name: str,
        company_domain: str,
        created_by_user_id: uuid.UUID,
    ) -> Tenant:
        if await self.get_by_domain(company_domain) is not None:
            raise DomainAlreadyRegisteredError(company_domain)
        if await self.get_by_subdomain(subdomain) is not None:
            raise SubdomainTakenError(subdomain)

        tenant = Tenant(
            tenant_id=tenant_id,
            subdomain=subdomain,
            company_name=company_name,
            company_domain=company_domain,
            created_by_user_id=created_by_user_id,
            status="PENDING",
        )
        self._session.add(tenant)
        await self._session.flush()
        return tenant
