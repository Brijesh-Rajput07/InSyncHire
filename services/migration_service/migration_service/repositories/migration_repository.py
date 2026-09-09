# LOCATION: services/migration_service/migration_service/repositories/migration_repository.py

"""
Repository layer for the `tenant_migrations` tracking table.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TenantMigration


class MigrationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def record_applied(
        self, tenant_id: uuid.UUID, alembic_version: str, applied_by_service: str = "migration_service"
    ) -> TenantMigration:
        record = TenantMigration(
            tenant_id=tenant_id,
            alembic_version=alembic_version,
            applied_by_service=applied_by_service,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_latest_for_tenant(self, tenant_id: uuid.UUID) -> TenantMigration | None:
        result = await self._session.execute(
            select(TenantMigration)
            .where(TenantMigration.tenant_id == tenant_id)
            .order_by(TenantMigration.applied_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def all_tenant_versions(self) -> dict[uuid.UUID, str]:
        """Latest known alembic_version per tenant — used by the
        system-admin 'run pending migrations across all tenants' command
        to decide which tenant DBs are behind head."""
        result = await self._session.execute(
            select(TenantMigration.tenant_id, TenantMigration.alembic_version, TenantMigration.applied_at)
            .order_by(TenantMigration.applied_at.desc())
        )
        latest: dict[uuid.UUID, str] = {}
        for tenant_id, alembic_version, _applied_at in result.all():
            if tenant_id not in latest:
                latest[tenant_id] = alembic_version
        return latest
