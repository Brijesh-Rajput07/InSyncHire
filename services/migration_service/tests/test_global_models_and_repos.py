# LOCATION: services/migration_service/tests/test_global_models_and_repos.py

"""
Tests for the insynchire_global ORM models + repository layer, run
against in-memory SQLite (see conftest.py for why).
"""

import asyncio
import uuid

import pytest

from migration_service.models import Base
from migration_service.repositories import (
    MigrationRepository,
    TenantNotFoundError,
    TenantRepository,
)
from shared.db import make_session_factory

from .conftest import build_test_engine


def test_create_pending_tenant_and_activate():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)

        tenant_id = uuid.uuid4()
        creator_id = uuid.uuid4()

        async with session_factory() as session:
            repo = TenantRepository(session)
            tenant = await repo.create_pending(
                tenant_id=tenant_id,
                subdomain="acme",
                company_name="Acme Corp",
                company_domain="acme.com",
                created_by_user_id=creator_id,
            )
            await session.commit()
            assert tenant.status == "PENDING"
            assert tenant.db_connection_string is None

        async with session_factory() as session:
            repo = TenantRepository(session)
            tenant = await repo.set_connection_string_and_activate(tenant_id, "encrypted-dsn-value")
            await session.commit()
            assert tenant.status == "ACTIVE"
            assert tenant.db_connection_string == "encrypted-dsn-value"

        async with session_factory() as session:
            fetched = await TenantRepository(session).get_by_id(tenant_id)
            assert fetched.subdomain == "acme"
            assert fetched.company_domain == "acme.com"

        await engine.dispose()

    asyncio.run(_run())


def test_get_by_id_raises_for_unknown_tenant():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            with pytest.raises(TenantNotFoundError):
                await TenantRepository(session).get_by_id(uuid.uuid4())

        await engine.dispose()

    asyncio.run(_run())


def test_mark_failed():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)
        tenant_id = uuid.uuid4()

        async with session_factory() as session:
            await TenantRepository(session).create_pending(
                tenant_id=tenant_id,
                subdomain="beta",
                company_name="Beta Inc",
                company_domain="beta.com",
                created_by_user_id=uuid.uuid4(),
            )
            await session.commit()

        async with session_factory() as session:
            tenant = await TenantRepository(session).mark_failed(tenant_id)
            await session.commit()
            assert tenant.status == "FAILED"

        await engine.dispose()

    asyncio.run(_run())


def test_migration_repository_tracks_versions():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)
        tenant_id = uuid.uuid4()

        async with session_factory() as session:
            await TenantRepository(session).create_pending(
                tenant_id=tenant_id,
                subdomain="gamma",
                company_name="Gamma LLC",
                company_domain="gamma.com",
                created_by_user_id=uuid.uuid4(),
            )
            await session.commit()

        async with session_factory() as session:
            migration_repo = MigrationRepository(session)
            await migration_repo.record_applied(tenant_id, "0001_initial")
            await session.commit()

        async with session_factory() as session:
            latest = await MigrationRepository(session).get_latest_for_tenant(tenant_id)
            assert latest.alembic_version == "0001_initial"

            all_versions = await MigrationRepository(session).all_tenant_versions()
            assert all_versions[tenant_id] == "0001_initial"

        await engine.dispose()

    asyncio.run(_run())


def test_list_active_only_returns_active_tenants():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)

        active_id, pending_id = uuid.uuid4(), uuid.uuid4()

        async with session_factory() as session:
            repo = TenantRepository(session)
            await repo.create_pending(
                tenant_id=active_id, subdomain="active-co", company_name="Active Co",
                company_domain="active.com", created_by_user_id=uuid.uuid4(),
            )
            await repo.create_pending(
                tenant_id=pending_id, subdomain="pending-co", company_name="Pending Co",
                company_domain="pending.com", created_by_user_id=uuid.uuid4(),
            )
            await session.commit()

        async with session_factory() as session:
            await TenantRepository(session).set_connection_string_and_activate(active_id, "dsn")
            await session.commit()

        async with session_factory() as session:
            active_tenants = await TenantRepository(session).list_active()
            assert {t.tenant_id for t in active_tenants} == {active_id}

        await engine.dispose()

    asyncio.run(_run())
