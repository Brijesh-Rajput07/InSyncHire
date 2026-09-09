# LOCATION: services/migration_service/migration_service/db_admin.py

"""
Low-level Postgres administrative operations for tenant provisioning.

This is the ONLY module in the whole system that runs a raw
`CREATE DATABASE` statement or invokes Alembic directly — every other
service goes through the repository layer against an already-existing
database. Keeping this concentrated in one small module makes the
"never run migrations inline in the API request path" rule (Section 2)
easy to audit: nothing outside this file and `services/provisioning_service.py`
touches DDL.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

_TENANT_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic_tenant.ini"
_TENANT_ALEMBIC_DIR = Path(__file__).resolve().parent.parent / "alembic_tenant"


def build_tenant_db_name(tenant_id: uuid.UUID) -> str:
    """Deterministic, DDL-safe database name for a tenant.

    Uses the UUID's hex form (no dashes) so the resulting identifier is
    always valid as a bare Postgres identifier without quoting.
    """
    return f"tenant_{tenant_id.hex}_db"


def render_dsn(template: str, db_name: str) -> str:
    return template.format(db_name=db_name)


async def create_tenant_database(db_name: str, admin_dsn: str) -> None:
    """Run `CREATE DATABASE <db_name>` against the admin/maintenance
    connection. Idempotent: if the database already exists (e.g. a
    retried Kafka message after a partial failure), this is a no-op
    rather than an error.

    Imports asyncpg lazily so this module — and everything that imports
    it for its pure helper functions like `build_tenant_db_name` — stays
    importable in environments/tests that don't have asyncpg installed
    or a Postgres instance reachable.
    """
    import asyncpg

    conn = await asyncpg.connect(dsn=admin_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if exists:
            return
        # CREATE DATABASE cannot run inside a transaction block and
        # cannot use bind parameters for the identifier — db_name is
        # always our own deterministic `tenant_<hex>_db` string (never
        # user-supplied), so building it into the statement is safe.
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


def run_tenant_migration_suite(tenant_dsn_sync: str) -> str:
    """Run the full tenant Alembic migration suite against `tenant_dsn_sync`
    and return the resulting head revision id.

    This is a blocking call (Alembic's `command.upgrade` is synchronous)
    — callers running inside an async context must wrap it with
    `asyncio.to_thread(...)`, which `provisioning_service.py` does.

    Imports alembic lazily for the same reason as create_tenant_database
    above: keeps this module importable without the dependency present.
    """
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(_TENANT_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_TENANT_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", tenant_dsn_sync)

    command.upgrade(cfg, "head")

    script_dir = ScriptDirectory.from_config(cfg)
    head_revision = script_dir.get_current_head()
    if head_revision is None:
        raise RuntimeError("Tenant Alembic migration suite has no revisions defined")
    return head_revision


def get_global_alembic_paths() -> tuple[Path, Path]:
    """Paths for the insynchire_global migration suite (separate from
    the per-tenant one above) — used by a one-time bootstrap script,
    not by per-tenant provisioning."""
    base = Path(__file__).resolve().parent.parent
    return base / "alembic_global.ini", base / "alembic_global"
