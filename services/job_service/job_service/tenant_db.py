# LOCATION: services/job_service/job_service/tenant_db.py

"""
Tenant DB connection resolution -- same scoped-down pattern as
tenant_service/tenant_db.py (Section 2/Task E's full connection-routing
middleware is still a future shared piece; each service that needs one
tenant DB per request builds this same way using `shared.db` until
enough services exist to justify extracting it).

Job Service additionally needs `list_active_tenants()`, which none of
the earlier services needed -- see services/public_board_service.py's
docstring for why (the interim public job board iterates every ACTIVE
tenant's DB directly, since Reporting Service, M12, doesn't exist yet
to provide the real aggregate).
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
        super().__init__(f"Tenant {tenant_id} is not ACTIVE (status={status})")
        self.tenant_id = tenant_id
        self.status = status


class TenantNotFoundError(Exception):
    pass


class TenantResolver:
    def __init__(self, *, global_session_factory, crypto: ConnectionStringCrypto):
        self._global_session_factory = global_session_factory
        self._crypto = crypto
        self._engine_cache: dict[uuid.UUID, AsyncEngine] = {}
        self._session_factory_cache: dict[uuid.UUID, async_sessionmaker[AsyncSession]] = {}

    async def _get_tenant_row(self, tenant_id: uuid.UUID) -> Tenant:
        async with self._global_session_factory() as session:
            result = await session.execute(select(Tenant).where(Tenant.tenant_id == tenant_id))
            tenant = result.scalar_one_or_none()
            if tenant is None:
                raise TenantNotFoundError(f"Tenant {tenant_id} not found")
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
        tenant = await self._get_tenant_row(tenant_id)
        session_factory = self._get_or_build_session_factory(tenant)
        session = session_factory()
        await set_tenant_context(session, tenant.tenant_id)
        return session, tenant

    async def list_active_tenants(self, limit: int) -> list[Tenant]:
        """Used only by the interim public board (see
        services/public_board_service.py) -- bounded by `limit` so a
        single request can't be made to scan an unbounded number of
        tenant DBs."""
        async with self._global_session_factory() as session:
            result = await session.execute(select(Tenant).where(Tenant.status == "ACTIVE").limit(limit))
            return list(result.scalars().all())

    async def dispose_all(self) -> None:
        for engine in self._engine_cache.values():
            await engine.dispose()
        self._engine_cache.clear()
        self._session_factory_cache.clear()