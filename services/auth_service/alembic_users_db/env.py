# LOCATION: services/auth_service/alembic_users_db/env.py

"""
Alembic environment for `users_db`.

Owned by Auth Service for now since it's the first consumer (creates
the minimal `user_profiles` row at candidate signup) -- M4 (candidate
profile/resume management) extends this SAME chain with `user_resumes`,
`user_applications_index`, `user_notifications`, NOT a second suite.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth_service.models import UsersDbBase  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = UsersDbBase.metadata


def _sync_dsn() -> str:
    return os.getenv(
        "USERS_DB_DSN_SYNC",
        os.getenv("USERS_DB_DSN", "postgresql://postgres:postgres@localhost:5433/users_db").replace(
            "+asyncpg", ""
        ),
    )


def run_migrations_offline() -> None:
    context.configure(url=_sync_dsn(), target_metadata=target_metadata, literal_binds=True)
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
