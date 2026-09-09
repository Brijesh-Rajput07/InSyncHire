# LOCATION: services/migration_service/README.md

# Migration Service (M1)

Headless service — **no HTTP routes** (Section 6). Its only two jobs:

1. Consume `tenant.signup_initiated` from Kafka, provision that tenant's
   Postgres database, run the tenant Alembic migration suite against
   it, and publish `migration.completed` + `tenant.created` (or
   `migration.failed` on error).
2. Provide a system-admin CLI command to bring every ACTIVE tenant DB
   up to the latest migration — never run inline in an API request.

## Install

Install in this order (this service depends on the two shared packages
built in M0 and alongside M1):

```bash
cd insynchire

# 1. insynchire-events (M0)
pip install -e shared/insynchire-events

# 2. shared.db helpers (M1)
pip install -e shared/shared-db

# 3. this service
pip install -e "services/migration_service[dev]"
```

## Run the tests (no Postgres/Kafka required)

```bash
cd services/migration_service
python -m pytest -q
```

Expected: `10 passed`.

**What these tests do and don't cover:** they run the full ORM +
repository + orchestration logic against in-memory SQLite, and mock out
exactly two Postgres-specific calls (`CREATE DATABASE` and running the
Alembic tenant suite). Before you deploy, also do the one-time real
integration check below.

## One-time real integration check (requires local Postgres)

```bash
# 1. Start a local Postgres (adjust as needed)
docker run --name insynchire-pg -e POSTGRES_PASSWORD=postgres -p 5433:5433 -d postgres:16

# 2. Create the insynchire_global database itself
psql -h localhost -U postgres -c "CREATE DATABASE insynchire_global;"

# 3. Copy and fill in the env file
cp .env.example .env
# generate and paste a real encryption key:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 4. Run the insynchire_global migration suite once
alembic -c alembic_global.ini upgrade head

# 5. Confirm the tenant Alembic suite is valid (dry parse, no DB needed)
python3 -c "
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config('alembic_tenant.ini')
cfg.set_main_option('script_location', 'alembic_tenant')
print(ScriptDirectory.from_config(cfg).get_current_head())
"
```

## Running the service for real

```bash
# Load your .env first (e.g. `export $(cat .env | xargs)` or use direnv/python-dotenv)

# Headless Kafka consumer — provisions tenants as signup events arrive
python -m migration_service.main serve

# System-admin command — bring every ACTIVE tenant DB up to head
python -m migration_service.main migrate-all
```

## Folder contents

```
services/migration_service/
├── pyproject.toml
├── .env.example
├── README.md
├── alembic_global.ini              ← config for the insynchire_global suite
├── alembic_global/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/0001_initial.py    ← tenants, tenant_migrations, global_users, global_user_resumes
├── alembic_tenant.ini               ← config for the per-tenant suite
├── alembic_tenant/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/0001_initial.py    ← organizations, tenant_user_memberships (+ RLS)
├── migration_service/
│   ├── __init__.py
│   ├── config.py                   ← env-based settings
│   ├── db_admin.py                 ← CREATE DATABASE + run Alembic (the only DDL-touching module)
│   ├── main.py                     ← `serve` (Kafka consumer) / `migrate-all` (CLI)
│   ├── models/
│   │   ├── base.py
│   │   └── global_models.py        ← Tenant, TenantMigration, GlobalUser, GlobalUserResume
│   ├── repositories/
│   │   ├── tenant_repository.py
│   │   └── migration_repository.py
│   └── services/
│       └── provisioning_service.py ← the core orchestration logic
└── tests/
    ├── conftest.py
    ├── test_db_admin.py
    ├── test_global_models_and_repos.py
    └── test_provisioning_service.py
```

## Why the tenant Alembic suite has no shared `Base.metadata`

Unlike `insynchire_global` (owned entirely by this service),
`tenant_<id>_db`'s schema is contributed by multiple future services —
Job Service adds `job_openings`/`job_applications` (M5), Interview
Service adds `interview_sessions`/`code_snapshots` (M8), etc. Rather
than one shared declarative model spanning services that don't know
about each other, every tenant-DB migration is a hand-written revision
in `alembic_tenant/versions/`, reviewed like any other schema change.
Each future milestone adds its migration to this *same* chain — do not
create a second tenant Alembic suite.

## RLS reminder

Every tenant table created here (and in every future tenant-DB
migration) must:
1. `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`
2. `CREATE POLICY ... USING (tenant_id = current_setting('app.current_tenant_id')::uuid)`

See `alembic_tenant/versions/20260101_0001_initial.py`'s `_enable_rls()`
helper — reuse that pattern for every new tenant table.
