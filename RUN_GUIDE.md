# LOCATION: RUN_GUIDE.md   (repo root)

# InSyncHire — How to Run What's Been Built So Far

Updated every time a new milestone (or backfill fix) is added.

## Full folder structure so far

```
insynchire/
├── RUN_GUIDE.md
├── LOCAL_APP_SETUP.md                ← running the real app (Postgres/Redis/Kafka), not just tests
├── shared/
│   ├── insynchire-events/            ← M0: Kafka event contract package (+ FIX-M0 agent events)
│   ├── shared-db/                    ← M1: shared async DB helpers (engine/session, RLS, GUID, crypto)
│   ├── auth-tokens/                  ← M3: shared encrypted-JWT token system (+ FIX-M2 fingerprint re-validation)
│   └── permissions/                  ← FIX-M3: canonical PERMISSION_MATRIX
└── services/
    ├── migration_service/            ← M1: tenant DB provisioning (+ FIX-M1 agent/process log tables)
    ├── auth_service/                 ← M2: signup (company + candidate), login, cookies (+ FIX-M2 users_db fix)
    └── tenant_service/               ← M3: company_admin bootstrap, invites, tenant selection (+ FIX-M3 matrix/edge cases)
```

(See each package's own README for its detailed internal file tree.)

## Setup — run in this exact order

```bash
cd insynchire
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e "shared/insynchire-events[dev]"
python -m pytest -q shared/insynchire-events
# -> 13 passed

pip install -e "shared/shared-db[dev]"
python -m pytest -q shared/shared-db
# -> 5 passed

pip install -e "shared/auth-tokens[dev]"
python -m pytest -q shared/auth-tokens
# -> 13 passed

pip install -e "shared/permissions[dev]"
python -m pytest -q shared/permissions
# -> 13 passed

pip install -e "services/migration_service[dev]"
python -m pytest -q services/migration_service
# -> 15 passed

pip install -e "services/auth_service[dev]"
python -m pytest -q services/auth_service
# -> 28 passed

pip install -e "services/tenant_service[dev]"
python -m pytest -q services/tenant_service
# -> 29 passed
```

**All seven together: 116 passed.** No Postgres/Redis/Kafka required for
tests — SQLite (including real temp-file SQLite standing in for tenant
DBs), fakeredis, and mocked Kafka publish stand in throughout.

**To run the actual app** (real Postgres/Redis/Kafka, real HTTP
requests, watching the Migration Service provision a tenant DB live),
see `LOCAL_APP_SETUP.md`.

## The FIX-M0 → FIX-M3 backfill (Section 4/4a of the project plan)

After M3 was built, the project plan's own gap list (Section 4) was
checked against what had actually been implemented, and several real
gaps were found and fixed — not because the plan document changed, but
because the actual build hadn't caught up with everything the plan's
own "backfill before M4" checklist called for:

| Fix | What was actually wrong | What changed |
|---|---|---|
| **FIX-M0** | The 6 `agent.*` Kafka topics + `GuardrailEvent` were simply never added to `insynchire-events` | Added additively — `topics.py` + `schemas.py` + tests. No existing schema changed. |
| **FIX-M1** | `agent_decision_logs`, `agent_guardrail_logs`, `process_logs` were missing from the tenant Alembic suite; the CLI command was named `migrate-all` instead of the plan's `migrate-all-tenants` | New revision `0003_agent_and_process_logs` added to the SAME tenant chain; CLI renamed (`migrate-all` kept as a legacy alias) |
| **FIX-M2** | Candidate signup wrote DIRECTLY to `users_db.user_profiles` from Auth Service (exactly the anti-pattern the plan warns about) — AND `session_fingerprint` was embedded in tokens but never actually re-validated on requests, a real security gap | Direct write removed (Auth Service now only publishes `user.registered`; M4 will own the write); `TokenService.decode_and_verify()`/`refresh()` now take `current_fingerprint` and reject + revoke on mismatch |
| **FIX-M3** | Tenant Service had per-route hardcoded role checks instead of one canonical matrix; expired invites returned 400 instead of 410; no "existing candidate account" confirmation step | New `shared/permissions` package with `PERMISSION_MATRIX` (Section 4a, verbatim + documented additions), wired into Tenant Service's routes; expired → 410, already-used → 409; candidate-account acceptance now requires explicit confirmation (428 until confirmed) |

Two of these (the fingerprint gap and the direct users_db write) were
genuine bugs worth knowing about even outside the context of "matching
the plan" — see each package's README for the technical detail.

## What each milestone proves

| Package | Proves |
|---|---|
| `insynchire-events` (M0/FIX-M0) | Every Kafka event — including the 6 agent.* events and GuardrailEvent — is schema-validated, retried, and DLQ-routed on failure |
| `shared-db` (M1) | GUID type round-trips on SQLite + Postgres; connection strings encrypt/decrypt; RLS statement well-formed and dialect-aware (no-ops safely on SQLite) |
| `migration_service` (M1/FIX-M1) | Tenant provisioning orchestration incl. the failure path; the tenant Alembic chain resolves to a single head including the FIX-M1 tables; CLI accepts both command names |
| `auth_service` (M2/FIX-M2) | Domain validation, OTP (incl. lockout), password hashing, and all three signup/login flows end to end — with NO users_db connection anywhere in its runtime wiring |
| `auth-tokens` (M3/FIX-M2) | The encrypted-payload RS256 token system, INCLUDING that a fingerprint-mismatched token is rejected AND revoked, and can't be retried even with the correct fingerprint afterward |
| `permissions` (FIX-M3) | The matrix's path-pattern matching (`{id}`, `/admin/*`), fail-closed default (unmapped route = denied), and that `"*"` correctly means "any authenticated caller regardless of role" (a bug I initially got wrong and caught via testing) |
| `tenant_service` (M3/FIX-M3) | company_admin bootstrap, domain-validated invites, invite acceptance (incl. 410/409/428 status codes and the candidate-confirmation flow), tenant-scoped token issuance, and matrix-driven role enforcement — through the real FastAPI app |

## Known Windows gotcha

If `pip install -e "shared/shared-db[dev]"` fails with "not a valid
editable requirement", check the folder name matches exactly — it must
be `shared-db` (hyphen), not `shared_db` (underscore). Same applies to
`insynchire-events`, `auth-tokens`, and `permissions`. `dir shared` will
show you what's actually there.

## Known pytest gotcha: run each package separately

Each service's `tests/` folder is its own Python package (has
`__init__.py`, needed for `from .conftest import ...` relative imports).
Running pytest across **multiple services in one command** will hit an
`ImportPathMismatchError` because of duplicate `tests` package names
across services — always run each package's tests as its own `pytest`
invocation (exactly as shown above).

## Cross-service configuration reminder

Auth Service, Tenant Service (and any future service that touches
tokens or tenant connection strings) must share:
- The exact same RS256 keypair + `TOKEN_PAYLOAD_ENCRYPTION_KEY`
  (`shared/auth-tokens/README.md`)
- The exact same `CONNECTION_STRING_ENCRYPTION_KEY` as Migration
  Service (so Tenant Service can decrypt tenant DSNs Migration Service
  encrypted)

These are called out in each service's `.env.example`.

## Next milestone

**M4 — users_db schema + candidate profile/resume management**
(Section 4): now that FIX-M2 removed Auth Service's direct write, M4's
dedicated service is the ONE place that will consume `user.registered`
and create the `user_profiles` row, plus add `user_resumes`,
`user_applications_index`, `user_notifications` — same users_db Alembic
chain (already scaffolded in `auth_service/alembic_users_db/` as a
reference), new revisions, not a second suite. Needed before Job
Service (M5) can handle applications.
