# LOCATION: services/migration_service/alembic_global/env.py

"""
Alembic environment for insynchire_global.

The DB URL always comes from the GLOBAL_DB_DSN env var (Section 10i —
no secrets/URLs hardcoded), converted to a sync driver since Alembic's
default migration runner is synchronous even though the app itself
talks to this DB asynchronously via `shared.db`.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `migration_service.models` importable when Alembic is invoked
# from the services/migration_service/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from migration_service.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_dsn() -> str:
    dsn = os.getenv(
        "GLOBAL_DB_DSN_SYNC",
        os.getenv(
            "GLOBAL_DB_DSN", "postgresql://postgres:postgres@localhost:5433/insynchire_global"
        ).replace("+asyncpg", ""),
    )
    return dsn


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_dsn(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _sync_dsn()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
