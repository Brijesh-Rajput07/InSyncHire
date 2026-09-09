# LOCATION: services/migration_service/migration_service/config.py

"""
Env-based configuration for the Migration Service.

All secrets come from environment variables only (Section 10i) —
nothing here is hardcoded. See services/migration_service/.env.example
for the full list with descriptions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MigrationServiceConfig:
    # insynchire_global connection (the control-plane DB this service
    # itself reads/writes via TenantRepository / MigrationRepository)
    global_db_dsn: str = os.getenv(
        "GLOBAL_DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5433/insynchire_global"
    )

    # Admin connection used ONLY to run `CREATE DATABASE tenant_xxx_db`.
    # Must point at a Postgres role with CREATEDB privilege, connected to
    # the `postgres` maintenance database (you cannot CREATE DATABASE
    # while connected to the database being created, or usually to any
    # database other than a maintenance one, depending on setup).
    postgres_admin_dsn: str = os.getenv(
        "POSTGRES_ADMIN_DSN", "postgresql://postgres:postgres@localhost:5433/postgres"
    )

    # Template used to build each tenant's own connection string once
    # its database exists. `{db_name}` is substituted with
    # `tenant_<hex>_db`.
    tenant_dsn_template: str = os.getenv(
        "TENANT_DSN_TEMPLATE",
        "postgresql+asyncpg://postgres:postgres@localhost:5433/{db_name}",
    )
    # Sync variant (asyncpg driver doesn't work with Alembic's default
    # sync migration runner) used specifically when invoking Alembic.
    tenant_dsn_template_sync: str = os.getenv(
        "TENANT_DSN_TEMPLATE_SYNC",
        "postgresql+psycopg2://postgres:postgres@localhost:5433/{db_name}",
    )

    kafka_consumer_group: str = os.getenv("MIGRATION_SERVICE_KAFKA_GROUP", "migration_service")


_cached: MigrationServiceConfig | None = None


def get_config() -> MigrationServiceConfig:
    global _cached
    if _cached is None:
        _cached = MigrationServiceConfig()
    return _cached
