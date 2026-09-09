# LOCATION: services/tenant_service/README.md

# Tenant Service (M3 — Task F)

FastAPI service that is BOTH an HTTP API (`/tenant/*`) AND a background
Kafka consumer in the same process (see `main.py`'s lifespan).

## What it does

1. **Bootstraps `company_admin`** — consumes `tenant.created` (published
   by Migration Service once M1 provisioning finishes) and creates the
   tenant's default Organization + assigns the tenant's creator as
   `company_admin` in `tenant_user_memberships`. This is the ONLY path
   that ever assigns `company_admin`.
2. **Invites users** (Task F) — `company_admin` invites by email,
   validated against the tenant's own corporate domain, stored in
   `invited_users`, publishes `user.invited`. Enforced via the shared
   `PERMISSION_MATRIX` (FIX-M3), not a hardcoded role check.
3. **Accepts invites** — verifies the invite token, creates the
   `tenant_user_memberships` row with the invited role, issues a
   tenant-scoped session immediately. FIX-M3: expired invites return
   `410 Gone`, already-used ones `409 Conflict`; if the accepting
   account is a `candidate` account_type, a `428 Precondition Required`
   asks for explicit confirmation before also granting company access.
4. **Tenant selection** — closes a gap from M2: a `company_user`'s
   global login token has `tenant_id`/`org_id`/`role` unset (Auth
   Service has no way to know which tenant applies). `POST
   /tenant/select` checks the caller's membership in a tenant (by
   subdomain) and issues a new, tenant-scoped token.

## New shared packages this milestone introduced

- `shared/auth-tokens` — the token issuance/verification system moved
  out of Auth Service into a shared package, since this service needs
  to both verify (`get_current_identity`) and issue (`tenant
  selection`, `accept invite`) tokens using the exact same scheme. See
  that package's README for why every service needs the SAME keys.
- `shared/permissions` (FIX-M3) — the canonical `PERMISSION_MATRIX`
  (Section 4a), imported here instead of hardcoding role lists at each
  route. `auth_dependency.enforce_permission_matrix()` is the
  dependency that consults it.

## Install

```bash
cd insynchire
pip install -e shared/insynchire-events
pip install -e shared/shared-db
pip install -e shared/auth-tokens
pip install -e shared/permissions
pip install -e "services/tenant_service[dev]"
```

## Run the tests (no Postgres/Redis/Kafka required)

```bash
cd services/tenant_service
python -m pytest -q
```

Expected: `29 passed`.

**What's genuinely exercised, not mocked:** the encrypt-then-connect
tenant DB resolution (`TenantResolver`) runs against a REAL temp-file
SQLite database with real encrypted connection strings — not a stand-in
for that logic. The full invite → accept → membership → tenant-scoped-
token flow is driven through the actual FastAPI app via httpx's ASGI
transport in `test_routes_integration.py`, including role-enforcement
checks (a non-admin gets 403, an unauthenticated caller gets 401, an
invite for the wrong tenant/domain is rejected).

**What still needs a real check before deploying:** actual Postgres
RLS enforcement (SQLite can't test that — see `_enable_rls()` in the
Migration Service's tenant Alembic revisions) and real Kafka delivery
of `tenant.created` end to end.

## Configuration gotchas (read before running for real)

- `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH` / `TOKEN_PAYLOAD_ENCRYPTION_KEY`
  **must be identical** to Auth Service's — otherwise tokens Auth
  Service issues won't verify here (and vice versa).
- `CONNECTION_STRING_ENCRYPTION_KEY` **must be identical** to Migration
  Service's — otherwise this service can't decrypt tenant connection
  strings Migration Service encrypted.

## Folder contents

```
services/tenant_service/
├── pyproject.toml
├── .env.example
├── README.md
├── tenant_service/
│   ├── __init__.py
│   ├── config.py
│   ├── auth_dependency.py       ← get_current_identity, require_role
│   ├── cookies.py
│   ├── dependencies.py
│   ├── main.py                  ← FastAPI app + background tenant.created consumer
│   ├── tenant_db.py             ← TenantResolver: decrypt + connect + RLS activate
│   ├── models/                  ← Tenant (global, read-only) + Organization/Membership/Invite (tenant DB)
│   ├── schemas/
│   ├── repositories/
│   ├── services/
│   │   ├── tenant_provisioning_consumer_service.py  ← tenant.created handler
│   │   ├── invite_service.py
│   │   ├── invite_acceptance_service.py
│   │   └── tenant_selection_service.py
│   └── routes/
│       ├── invite_routes.py
│       └── selection_routes.py
└── tests/
    ├── conftest.py
    ├── test_tenant_db.py
    ├── test_invite_service.py
    ├── test_invite_acceptance_service.py
    ├── test_tenant_provisioning_consumer_service.py
    ├── test_tenant_selection_service.py
    ├── test_auth_dependency.py
    └── test_routes_integration.py
```

## Why `company_admin` can't be invited

`InviteUserRequest.role` (see `schemas/invite_schemas.py`) only accepts
`recruiter | interviewer | observer` — deliberately excluding
`company_admin`. The only path to `company_admin` is being the
tenant's original creator (bootstrapped automatically on
`tenant.created`). Promoting an existing member TO `company_admin` is a
role-change operation, intentionally out of scope for the invite flow
— it would need its own audited endpoint (a future milestone), not be
reachable by anyone who merely receives an invite link.
