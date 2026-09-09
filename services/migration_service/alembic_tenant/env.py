# LOCATION: services/migration_service/alembic_tenant/env.py

"""
Alembic environment for the per-tenant migration suite.

Unlike alembic_global/env.py, there is no single shared SQLAlchemy
`Base.metadata` here — later milestones (Job Service, Interview
Service, etc.) each own their slice of the tenant schema and will add
their own hand-written revisions to this same `versions/` chain rather
than autogenerating against a combined model. `target_metadata = None`
reflects that deliberately: every tenant revision is explicit SQL via
`op.*` calls, reviewed by hand, never auto-diffed.

The DSN is injected programmatically by `db_admin.run_tenant_migration_suite()`
via `cfg.set_main_option("sqlalchemy.url", ...)` — never read from an env
var here, since this same env.py runs against a different tenant DSN on
every invocation.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
