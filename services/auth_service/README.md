# LOCATION: services/auth_service/README.md

# Auth Service (M2 — Tasks C + D)

FastAPI service owning all `/auth/*` and `/signup/*` routes (Section 3).

## What it does

- **Company signup** (Task C): corporate domain validation (blocklist +
  MX record check) → OTP → on verify: creates `global_users` +
  `tenants` (status=PENDING) → publishes `tenant.signup_initiated`
  (Migration Service, M1, picks this up and provisions the tenant DB).
- **Candidate signup** (Task D): any email accepted → OTP → on verify:
  creates `global_users` → publishes `user.registered` → issues
  encrypted httpOnly cookies (logged in immediately). **FIX-M2 update:**
  this no longer writes directly to `users_db.user_profiles` — Auth
  Service publishes the event and a future M4 service owns creating
  that row. The `alembic_users_db/` suite and `UserProfile` model still
  live in this folder as a schema reference for M4, but nothing in
  Auth Service's runtime wiring connects to users_db anymore.
- **Login** (Task D): verifies credentials, issues encrypted httpOnly cookies.
- **Refresh**: rotates the refresh token on every use.
- **Logout**: revokes both cookies' tokens via the Redis denylist.

## Install

```bash
cd insynchire
pip install -e shared/insynchire-events
pip install -e shared/shared-db
pip install -e shared/auth-tokens
pip install -e "services/auth_service[dev]"
```

## Run the tests (no Postgres/Redis/Kafka required)

```bash
cd services/auth_service
python -m pytest -q
```

Expected: `28 passed`.

**Note (M3):** the token issuance/verification system that used to live
entirely in this service (`services/token_service.py`) moved to the
shared `auth_tokens` package during M3, since Tenant Service needs the
exact same encrypted-JWT scheme. `auth_service/services/token_service.py`
is now a thin re-export — nothing else changed, and the corresponding
tests moved to `shared/auth-tokens/tests/` (9 tests, run separately).

**What's covered without real infra:** every service (domain validation,
OTP, password hashing, the encrypted-JWT token system including expiry/
revocation/refresh-rotation, and the three signup/login orchestrators)
is tested for real against SQLite + fakeredis. `test_routes_integration.py`
additionally drives the actual FastAPI app through httpx's ASGI
transport, proving the dependency wiring in `dependencies.py` and every
route in `routes/` work end to end — not just the service layer in isolation.

**What still needs a real check before deploying:** the actual DNS MX
lookup (`domain_validation_service.check_mx_record`, tested via a
stubbed checker here) and Kafka publish (tested via a `FakePublisher`)
should be exercised once against real infra.

## users_db schema reference (for M4 — not used by Auth Service at runtime)

The `alembic_users_db/` suite and `UserProfile` model in this folder
exist only as a starting reference for M4's dedicated service — Auth
Service itself has no runtime connection to users_db (FIX-M2). If you
want to inspect the schema they'd create:

```bash
# Create the users_db database (only needed if you're testing this schema directly)
psql -h localhost -U postgres -c "CREATE DATABASE users_db;"
cp .env.example .env   # fill in USERS_DB_DSN
alembic -c alembic_users_db.ini upgrade head
```

## Running the service

```bash
uvicorn auth_service.main:app --reload --port 8001
```

Try it:
```bash
curl -X POST http://localhost:8001/signup/candidate \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@example.com","full_name":"Jane Doe","password":"super-secret-123"}'
```

## Folder contents

```
services/auth_service/
├── pyproject.toml
├── .env.example
├── README.md
├── alembic_users_db.ini
├── alembic_users_db/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/20260101_0001_initial.py   ← user_profiles table
├── auth_service/
│   ├── __init__.py
│   ├── config.py
│   ├── cookies.py                          ← httpOnly cookie set/clear helpers
│   ├── dependencies.py                     ← FastAPI DI wiring
│   ├── main.py                             ← FastAPI app
│   ├── data/public_domain_blocklist.txt
│   ├── models/                             ← Tenant, GlobalUser, UserProfile (reference only, see above)
│   ├── schemas/                            ← Pydantic request/response shapes
│   ├── repositories/                       ← tenants, global_users, user_profiles (reference only, see above)
│   ├── services/
│   │   ├── domain_validation_service.py    ← blocklist + MX check
│   │   ├── otp_service.py                  ← Redis-backed OTP, attempts, lockout
│   │   ├── password_service.py             ← bcrypt hash/verify
│   │   ├── token_service.py                ← re-export of shared auth_tokens (M3)
│   │   ├── company_signup_service.py       ← Task C orchestration
│   │   ├── candidate_signup_service.py     ← Task D signup orchestration
│   │   └── login_service.py                ← Task D login orchestration
│   └── routes/
│       ├── signup_routes.py
│       └── auth_routes.py
└── tests/
    ├── conftest.py
    ├── test_domain_validation_service.py
    ├── test_otp_service.py
    ├── test_password_service.py
    ├── test_company_signup_service.py
    ├── test_candidate_signup_service.py
    ├── test_login_service.py
    └── test_routes_integration.py
```

## Why the token payload is encrypted AND signed

JWTs are signed (integrity — nobody can forge or tamper with one
without the private key) but by default **not confidential** — anyone
can base64-decode a JWT's claims and read them. Section 10c requires
the actual sensitive fields (`user_id`, `tenant_id`, `org_id`, `role`,
`session_fingerprint`) to stay unreadable even if the JWT itself is
decoded, e.g. by something logging raw cookie values. So:

1. Build the payload → AES-encrypt it (Fernet) → get ciphertext
2. Put `{"data": ciphertext, "jti": ..., "exp": ..., "iat": ...}` as the
   JWT claims → sign with RS256

Decoding the JWT without the RS256 public key fails entirely (bad
signature). Decoding it WITH the public key (which is not secret — it
only verifies, it can't forge) still only gets you the ciphertext in
`data`, not the actual user_id/tenant_id/role. You need the Fernet key
too. `test_token_service.py::test_issued_jwt_payload_is_actually_encrypted_not_plaintext`
proves this directly.

## RS256 keypair persistence

`token_service.generate_rsa_keypair_pem()` exists only for local dev/test
convenience (`dependencies.py` falls back to it if `JWT_PRIVATE_KEY_PATH`
isn't set). **Never rely on this in a real deployment** — every process
restart would generate a new keypair and instantly invalidate every
outstanding session. Always configure real, persisted keys via
`JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH`.
