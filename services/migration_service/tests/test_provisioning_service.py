# LOCATION: services/migration_service/tests/test_provisioning_service.py

"""
Tests for ProvisioningService -- the core orchestration logic of M1.

We mock exactly two things: `create_tenant_database` and
`run_tenant_migration_suite`, both of which require a real Postgres
instance and are the only Postgres-specific pieces of this flow.
Everything else (repository writes, event publishing, error handling,
the FAILED-status path) is exercised for real against in-memory SQLite,
so this test suite genuinely proves the orchestration logic is correct
-- only the two Postgres-admin calls are stubbed.

Before deploying, also run this service's `serve` command against a
real local Postgres + Kafka (docker-compose, Task P) at least once to
validate the two mocked calls too.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from cryptography.fernet import Fernet

from insynchire_events.schemas import TenantSignupInitiatedEvent
from insynchire_events.topics import Topics
from migration_service.config import MigrationServiceConfig
from migration_service.models import Base
from migration_service.repositories import TenantRepository
from migration_service.services.provisioning_service import (
    ProvisioningError,
    ProvisioningService,
)
from shared.db import make_session_factory
from shared.db.crypto import ConnectionStringCrypto

from .conftest import build_test_engine


class FakePublisher:
    """Captures every published event instead of touching Kafka."""

    def __init__(self):
        self.published: list[tuple[str, object]] = []

    async def publish(self, topic: str, event) -> None:
        self.published.append((topic, event))


async def _seed_pending_tenant(session_factory, tenant_id: uuid.UUID) -> None:
    async with session_factory() as session:
        await TenantRepository(session).create_pending(
            tenant_id=tenant_id,
            subdomain="acme",
            company_name="Acme Corp",
            company_domain="acme.com",
            created_by_user_id=uuid.uuid4(),
        )
        await session.commit()


def test_handle_signup_success_path(monkeypatch):
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)

        tenant_id = uuid.uuid4()
        await _seed_pending_tenant(session_factory, tenant_id)

        # Mock the two Postgres-specific calls
        created_dbs = []

        async def fake_create_tenant_database(db_name, admin_dsn):
            created_dbs.append(db_name)

        def fake_run_tenant_migration_suite(tenant_dsn_sync):
            return "0001_initial"

        import migration_service.services.provisioning_service as ps_module

        monkeypatch.setattr(ps_module, "create_tenant_database", fake_create_tenant_database)
        monkeypatch.setattr(ps_module, "run_tenant_migration_suite", fake_run_tenant_migration_suite)

        publisher = FakePublisher()
        service = ProvisioningService(
            config=MigrationServiceConfig(),
            global_session_factory=session_factory,
            publish=publisher.publish,
            crypto=ConnectionStringCrypto(key=Fernet.generate_key().decode()),
        )

        event = TenantSignupInitiatedEvent(
            trace_id="trace-1",
            tenant_id=tenant_id,
            subdomain="acme",
            company_name="Acme Corp",
            company_domain="acme.com",
            created_by_user_id=uuid.uuid4(),
        )

        await service.handle_signup(event)

        # Tenant DB was "created" and tenant flipped to ACTIVE with an
        # encrypted connection string stored
        assert len(created_dbs) == 1
        async with session_factory() as session:
            tenant = await TenantRepository(session).get_by_id(tenant_id)
            assert tenant.status == "ACTIVE"
            assert tenant.db_connection_string is not None
            assert "postgresql" not in tenant.db_connection_string  # it's encrypted, not plaintext

        # Correct events published, in order: migration.completed then tenant.created
        topics_published = [t for t, _ in publisher.published]
        assert topics_published == [Topics.MIGRATION_COMPLETED.value, Topics.TENANT_CREATED.value]

        await engine.dispose()

    asyncio.run(_run())


def test_handle_signup_failure_path_marks_tenant_failed_and_publishes(monkeypatch):
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)

        tenant_id = uuid.uuid4()
        await _seed_pending_tenant(session_factory, tenant_id)

        async def fake_create_tenant_database(db_name, admin_dsn):
            return None

        def fake_run_tenant_migration_suite_raises(tenant_dsn_sync):
            raise RuntimeError("simulated Alembic failure")

        import migration_service.services.provisioning_service as ps_module

        monkeypatch.setattr(ps_module, "create_tenant_database", fake_create_tenant_database)
        monkeypatch.setattr(
            ps_module, "run_tenant_migration_suite", fake_run_tenant_migration_suite_raises
        )

        publisher = FakePublisher()
        service = ProvisioningService(
            config=MigrationServiceConfig(),
            global_session_factory=session_factory,
            publish=publisher.publish,
            crypto=ConnectionStringCrypto(key=Fernet.generate_key().decode()),
        )

        event = TenantSignupInitiatedEvent(
            trace_id="trace-2",
            tenant_id=tenant_id,
            subdomain="acme",
            company_name="Acme Corp",
            company_domain="acme.com",
            created_by_user_id=uuid.uuid4(),
        )

        with pytest.raises(ProvisioningError):
            await service.handle_signup(event)

        # Tenant marked FAILED, not left dangling as PENDING
        async with session_factory() as session:
            tenant = await TenantRepository(session).get_by_id(tenant_id)
            assert tenant.status == "FAILED"

        # migration.failed published, and NOT migration.completed/tenant.created
        topics_published = [t for t, _ in publisher.published]
        assert topics_published == [Topics.MIGRATION_FAILED.value]

        await engine.dispose()

    asyncio.run(_run())
