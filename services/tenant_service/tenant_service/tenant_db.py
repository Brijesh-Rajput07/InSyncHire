# LOCATION: services/tenant_service/tenant_service/tenant_db.py

"""
Tenant DB connection resolution.

This is a deliberately SCOPED-DOWN version of the full connection
routing middleware described in Section 2/Task E — that middleware
(PgBouncer pooling, Redis-cached connection strings, per-request
injection into `request.state` for every service) is still a future
piece of shared infrastructure, built when enough services need it at
once to justify it. For M3, Tenant Service only needs to open a
connection to ONE tenant DB per request/event and activate RLS on it —
so that's all this module does, using the same building blocks
(`shared.db`) that the real middleware will eventually use too.

Engines are cached per tenant_id for the lifetime of the process so we
aren't building a new connection pool on every request.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from shared.db import make_engine, make_session_factory, set_tenant_context
from shared.db.crypto import ConnectionStringCrypto

from .models import Tenant


class TenantNotActiveError(Exception):
    def __init__(self, tenant_id: uuid.UUID, status: str):
        super().__init__(f"Tenant {tenant_id} is not ACTIVE (status={status}) — cannot connect yet")
        self.tenant_id = tenant_id
        self.status = status


class TenantNotFoundError(Exception):
    pass


class TenantResolver:
    """Resolves a tenant_id (or subdomain) to a ready-to-use, RLS-activated
    session for that tenant's database."""

    def __init__(self, *, global_session_factory, crypto: ConnectionStringCrypto):
        self._global_session_factory = global_session_factory
        self._crypto = crypto
        self._engine_cache: dict[uuid.UUID, AsyncEngine] = {}
        self._session_factory_cache: dict[uuid.UUID, async_sessionmaker[AsyncSession]] = {}

    async def _get_tenant_row(self, *, tenant_id: uuid.UUID | None = None, subdomain: str | None = None) -> Tenant:
        async with self._global_session_factory() as session:
            if tenant_id is not None:
                result = await session.execute(select(Tenant).where(Tenant.tenant_id == tenant_id))
            elif subdomain is not None:
                result = await session.execute(select(Tenant).where(Tenant.subdomain == subdomain))
            else:
                raise ValueError("Must provide tenant_id or subdomain")
            tenant = result.scalar_one_or_none()
            if tenant is None:
                raise TenantNotFoundError("Tenant not found")
            return tenant

    def _get_or_build_session_factory(self, tenant: Tenant) -> async_sessionmaker[AsyncSession]:
        if tenant.tenant_id in self._session_factory_cache:
            return self._session_factory_cache[tenant.tenant_id]

        if tenant.status != "ACTIVE" or not tenant.db_connection_string:
            raise TenantNotActiveError(tenant.tenant_id, tenant.status)

        decrypted_dsn = self._crypto.decrypt(tenant.db_connection_string)
        engine = make_engine(decrypted_dsn)
        session_factory = make_session_factory(engine)

        self._engine_cache[tenant.tenant_id] = engine
        self._session_factory_cache[tenant.tenant_id] = session_factory
        return session_factory

    async def get_session_for_tenant_id(self, tenant_id: uuid.UUID) -> tuple[AsyncSession, Tenant]:
        """Returns an open AsyncSession with RLS already activated for
        `tenant_id`, plus the Tenant row (subdomain/company_name/etc.
        often needed alongside). Caller is responsible for closing the
        session (use `async with` — the session itself supports it)."""
        tenant = await self._get_tenant_row(tenant_id=tenant_id)
        session_factory = self._get_or_build_session_factory(tenant)
        session = session_factory()
        await set_tenant_context(session, tenant.tenant_id)
        return session, tenant

    async def get_session_for_subdomain(self, subdomain: str) -> tuple[AsyncSession, Tenant]:
        tenant = await self._get_tenant_row(subdomain=subdomain)
        session_factory = self._get_or_build_session_factory(tenant)
        session = session_factory()
        await set_tenant_context(session, tenant.tenant_id)
        return session, tenant

    async def dispose_all(self) -> None:
        for engine in self._engine_cache.values():
            await engine.dispose()
        self._engine_cache.clear()
        self._session_factory_cache.clear()
