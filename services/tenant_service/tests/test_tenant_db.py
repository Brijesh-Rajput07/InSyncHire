# LOCATION: services/tenant_service/tests/test_tenant_db.py

"""
Tests for TenantResolver, exercising the REAL decrypt-then-connect
path (see conftest.py's seed_active_tenant) rather than mocking it.
"""

import asyncio
import uuid

import pytest
from shared.db import make_session_factory
from tenant_service.models import GlobalBase
from tenant_service.tenant_db import TenantNotActiveError, TenantNotFoundError, TenantResolver

from .conftest import build_global_test_engine, build_test_crypto, seed_active_tenant


def test_resolve_by_tenant_id_returns_working_session():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        tenant = await seed_active_tenant(session_factory, crypto, subdomain="acme")
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)

        session, resolved_tenant = await resolver.get_session_for_tenant_id(tenant.tenant_id)
        assert resolved_tenant.subdomain == "acme"

        # Session actually works -- query the (empty) organizations table
        from sqlalchemy import text

        result = await session.execute(text("SELECT COUNT(*) FROM organizations"))
        assert result.scalar() == 0
        await session.close()

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_resolve_by_subdomain():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        await seed_active_tenant(session_factory, crypto, subdomain="beta-co")
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)

        session, tenant = await resolver.get_session_for_subdomain("beta-co")
        assert tenant.subdomain == "beta-co"
        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_unknown_tenant_id_raises():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        resolver = TenantResolver(global_session_factory=session_factory, crypto=build_test_crypto())

        with pytest.raises(TenantNotFoundError):
            await resolver.get_session_for_tenant_id(uuid.uuid4())

        await engine.dispose()

    asyncio.run(_run())


def test_non_active_tenant_raises():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        from tenant_service.models import Tenant as GlobalTenantModel

        pending_tenant = GlobalTenantModel(
            tenant_id=uuid.uuid4(), subdomain="pending-co", company_name="Pending Co",
            company_domain="pending.com", db_connection_string=None, status="PENDING",
            created_by_user_id=uuid.uuid4(),
        )
        async with session_factory() as session:
            session.add(pending_tenant)
            await session.commit()

        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
        with pytest.raises(TenantNotActiveError):
            await resolver.get_session_for_tenant_id(pending_tenant.tenant_id)

        await engine.dispose()

    asyncio.run(_run())


def test_engine_is_cached_across_calls():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        tenant = await seed_active_tenant(session_factory, crypto, subdomain="cached-co")
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)

        s1, _ = await resolver.get_session_for_tenant_id(tenant.tenant_id)
        await s1.close()
        s2, _ = await resolver.get_session_for_tenant_id(tenant.tenant_id)
        await s2.close()

        assert len(resolver._engine_cache) == 1  # noqa: SLF001 -- verifying caching behavior directly

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())
