# LOCATION: services/migration_service/migration_service/services/provisioning_service.py

"""
Core tenant provisioning logic (Section: Tenant Onboarding Flow, step 2).

Orchestrates, for one `tenant.signup_initiated` event:
  1. Create the tenant's Postgres database
  2. Run the full tenant Alembic migration suite against it
  3. Encrypt the resulting connection string and store it + activate
     the tenant in insynchire_global
  4. Record the applied migration version in tenant_migrations
  5. Publish migration.completed + tenant.created (success path), or
     migration.failed (failure path)

This is intentionally the ONLY place these steps are wired together —
route handlers / Kafka consumer entrypoints call into this, they never
contain this orchestration themselves (repository pattern, Section 6).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Awaitable, Callable, Protocol

from insynchire_events.schemas import (
    BaseEvent,
    MigrationCompletedEvent,
    MigrationFailedEvent,
    TenantCreatedEvent,
    TenantSignupInitiatedEvent,
)
from insynchire_events.topics import Topics
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.db.crypto import ConnectionStringCrypto

from ..config import MigrationServiceConfig
from ..db_admin import build_tenant_db_name, create_tenant_database, render_dsn, run_tenant_migration_suite
from ..repositories import MigrationRepository, TenantRepository

PublishFn = Callable[[str, BaseEvent], Awaitable[None]]


class ProvisioningError(Exception):
    """Raised when provisioning fails after publishing migration.failed,
    so the Kafka consumer's own DLQ-routing logic (insynchire_events)
    also captures it."""


class ProvisioningService:
    def __init__(
        self,
        *,
        config: MigrationServiceConfig,
        global_session_factory: async_sessionmaker[AsyncSession],
        publish: PublishFn,
        crypto: ConnectionStringCrypto,
    ):
        self._config = config
        self._global_session_factory = global_session_factory
        self._publish = publish
        self._crypto = crypto

    async def handle_signup(self, event: TenantSignupInitiatedEvent) -> None:
        """Entry point wired to Topics.TENANT_SIGNUP_INITIATED via
        insynchire_events.subscribe() in main.py."""
        started_at = time.monotonic()
        db_name = build_tenant_db_name(event.tenant_id)

        try:
            await create_tenant_database(db_name, self._config.postgres_admin_dsn)

            tenant_dsn_sync = render_dsn(self._config.tenant_dsn_template_sync, db_name)
            alembic_version = await asyncio.to_thread(run_tenant_migration_suite, tenant_dsn_sync)

            tenant_dsn_async = render_dsn(self._config.tenant_dsn_template, db_name)
            encrypted_dsn = self._crypto.encrypt(tenant_dsn_async)

            async with self._global_session_factory() as session:
                tenant_repo = TenantRepository(session)
                migration_repo = MigrationRepository(session)
                await tenant_repo.set_connection_string_and_activate(event.tenant_id, encrypted_dsn)
                await migration_repo.record_applied(event.tenant_id, alembic_version)
                await session.commit()

            duration_ms = int((time.monotonic() - started_at) * 1000)

            await self._publish(
                Topics.MIGRATION_COMPLETED.value,
                MigrationCompletedEvent(
                    trace_id=event.trace_id,
                    tenant_id=event.tenant_id,
                    alembic_version=alembic_version,
                    duration_ms=duration_ms,
                ),
            )
            await self._publish(
                Topics.TENANT_CREATED.value,
                TenantCreatedEvent(
                    trace_id=event.trace_id,
                    tenant_id=event.tenant_id,
                    subdomain=event.subdomain,
                    company_domain=event.company_domain,
                ),
            )

        except Exception as exc:  # noqa: BLE001 - deliberately broad: any failure here is a provisioning failure
            await self._mark_failed_best_effort(event.tenant_id)
            await self._publish(
                Topics.MIGRATION_FAILED.value,
                MigrationFailedEvent(
                    trace_id=event.trace_id,
                    tenant_id=event.tenant_id,
                    attempted_alembic_version="head",
                    error_message=str(exc),
                ),
            )
            raise ProvisioningError(f"Provisioning failed for tenant {event.tenant_id}: {exc}") from exc

    async def _mark_failed_best_effort(self, tenant_id: uuid.UUID) -> None:
        """Attempt to flip the tenant's status to FAILED so support staff
        can see it in the admin dashboard. Deliberately swallows its own
        errors — we're already inside an exception handler and must not
        let a secondary DB error mask the original failure."""
        try:
            async with self._global_session_factory() as session:
                await TenantRepository(session).mark_failed(tenant_id)
                await session.commit()
        except Exception:  # noqa: BLE001
            pass


class RunPendingMigrationsResult(Protocol):
    tenant_id: uuid.UUID
    previous_version: str | None
    new_version: str


async def run_pending_migrations_for_all_tenants(
    *,
    config: MigrationServiceConfig,
    global_session_factory: async_sessionmaker[AsyncSession],
) -> list[dict]:
    """System-admin-triggered command (Section 3, Migration Service):
    iterates every ACTIVE tenant, checks its last-recorded alembic
    version against the current head, and re-runs the tenant migration
    suite for any tenant that's behind. Never runs inline in an API
    request path — this is invoked from a CLI entrypoint (see main.py's
    `run-pending-migrations` command).
    """
    results: list[dict] = []
    async with global_session_factory() as session:
        tenant_repo = TenantRepository(session)
        migration_repo = MigrationRepository(session)
        tenants = await tenant_repo.list_active()
        latest_versions = await migration_repo.all_tenant_versions()

    for tenant in tenants:
        db_name = build_tenant_db_name(tenant.tenant_id)
        tenant_dsn_sync = render_dsn(config.tenant_dsn_template_sync, db_name)
        previous_version = latest_versions.get(tenant.tenant_id)

        new_version = await asyncio.to_thread(run_tenant_migration_suite, tenant_dsn_sync)

        if new_version != previous_version:
            async with global_session_factory() as session:
                await MigrationRepository(session).record_applied(tenant.tenant_id, new_version)
                await session.commit()

        results.append(
            {
                "tenant_id": tenant.tenant_id,
                "previous_version": previous_version,
                "new_version": new_version,
                "changed": new_version != previous_version,
            }
        )

    return results
