# LOCATION: LOCAL_APP_SETUP.md   (repo root)

# Running the whole app locally (not just tests)

`RUN_GUIDE.md` covers installing packages and running each package's
**test suite** (fast, no real infra needed). This guide is different —
it walks through actually **running the app**: real Postgres, real
Redis, real Kafka, real HTTP requests.

There's no `docker-compose.yml` yet (that's Task P, later in the build
order) — for now we start each piece by hand with `docker run`.

---

## 0. Prerequisites

- Docker Desktop installed and running (simplest way to get Postgres/Redis/Kafka on Windows)
- Python 3.11+ with the M0–M3 packages already installed (see `RUN_GUIDE.md`)

If you don't want Docker, you can install Postgres/Redis/Kafka natively
instead — just adjust the connection strings in step 3 accordingly.

---

## 1. Start Postgres, Redis, and Kafka

Open PowerShell and run each of these (one-time; they'll keep running
in the background as Docker containers):

```powershell
docker run --name insynchire-pg -e POSTGRES_PASSWORD=postgres -p 5433:5433 -d postgres:16

docker run --name insynchire-redis -p 6379:6379 -d redis:7

docker run --name insynchire-kafka -p 9092:9092 -d apache/kafka:3.7.0
```

Check they're all up:
```powershell
docker ps
```
You should see three containers running. (Next time you just need
`docker start insynchire-pg insynchire-redis insynchire-kafka` instead
of `docker run` — no need to recreate them.)

---

## 2. Create the databases

```powershell
docker exec -it insynchire-pg psql -U postgres -c "CREATE DATABASE insynchire_global;"
docker exec -it insynchire-pg psql -U postgres -c "CREATE DATABASE users_db;"
```

(Tenant databases like `tenant_<id>_db` are created automatically by
the Migration Service when a company signs up — you don't create those
by hand.)

---

## 3. Configure environment variables

Both services read from a `.env` file. Copy the examples and fill them in:

```powershell
cd services\migration_service
copy .env.example .env

cd ..\auth_service
copy .env.example .env

cd ..\tenant_service
copy .env.example .env
```

The defaults in all three `.env.example` files already point at
`localhost:5433` / `localhost:6379` / `localhost:9092`, which matches
the Docker containers above, so for local dev you mostly just need to
generate two secrets:

```powershell
# Connection-string encryption key -- goes in BOTH migration_service/.env
# AND tenant_service/.env, with the EXACT SAME VALUE (Tenant Service
# decrypts tenant connection strings Migration Service encrypted).
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Paste that same value into:
- `services/migration_service/.env` as `CONNECTION_STRING_ENCRYPTION_KEY=...`
- `services/tenant_service/.env` as `CONNECTION_STRING_ENCRYPTION_KEY=...` (SAME value)

```powershell
# Token payload encryption key -- goes in BOTH auth_service/.env AND
# tenant_service/.env, with the EXACT SAME VALUE (Tenant Service verifies
# and issues tokens using the same scheme as Auth Service).
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Paste that same value into:
- `services/auth_service/.env` as `TOKEN_PAYLOAD_ENCRYPTION_KEY=...`
- `services/tenant_service/.env` as `TOKEN_PAYLOAD_ENCRYPTION_KEY=...` (SAME value)

```powershell
cd services\auth_service
openssl genrsa -out jwt_private.pem 2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```
(`JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH` in `.env.example` already
point at these filenames.) If you don't have `openssl` on Windows, it
ships with Git for Windows — run it from "Git Bash" instead of PowerShell.

`services/tenant_service/.env.example`'s `JWT_PRIVATE_KEY_PATH` /
`JWT_PUBLIC_KEY_PATH` already point at `../auth_service/jwt_private.pem`
/ `../auth_service/jwt_public.pem` — i.e. it reuses the SAME key files
you just generated, rather than needing its own copy. That's
deliberate: both services must use the identical keypair.

**Important:** `services/auth_service/.env.example` sets
`OTP_DEBUG_LOG_ENABLED=true`, and `services/tenant_service/.env.example`
sets `INVITE_DEBUG_LOG_ENABLED=true`. Keep both `true` for now — since
the Notification Service (email sending) isn't built until M7, these
are currently the *only* way to see the OTP code / invite link you need
to complete signup and invite flows. They just print to each service's
console log. Never set either to `true` in a real deployment.

Now load the `.env` files into your shell session. PowerShell doesn't
auto-load `.env` files, so either use a tool like `direnv`, or load
manually each time:

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
    }
}
```
Run that from inside each service's folder before starting it.

---

## 4. Run the database migrations

```powershell
cd services\migration_service
# (load .env as above, then:)
alembic -c alembic_global.ini upgrade head
```

```powershell
cd ..\auth_service
# (load .env as above, then:)
alembic -c alembic_users_db.ini upgrade head
```

This creates all the tables in `insynchire_global` and `users_db`. You
can confirm with:
```powershell
docker exec -it insynchire-pg psql -U postgres -d insynchire_global -c "\dt"
docker exec -it insynchire-pg psql -U postgres -d users_db -c "\dt"
```

(Tenant Service needs no separate migration step of its own — it reads
`insynchire_global` and connects to whichever `tenant_<id>_db` already
got created and migrated by the Migration Service in step 7 below.)

---

## 5. Start the services

You need **three terminals** open at once, from the repo root.

**Terminal 1 — Migration Service** (headless Kafka consumer; provisions
tenant DBs when someone signs up as a company):
```powershell
cd services\migration_service
# (load .env)
python -m migration_service.main serve
```
Leave this running. It'll sit quietly until a company signup happens.

**Terminal 2 — Auth Service** (the actual HTTP API):
```powershell
cd services\auth_service
# (load .env)
uvicorn auth_service.main:app --reload --port 8001
```
You should see `Uvicorn running on http://127.0.0.1:8001`.

**Terminal 3 — Tenant Service** (HTTP API on a different port, PLUS a
background consumer for `tenant.created` in the same process):
```powershell
cd services\tenant_service
# (load .env)
uvicorn tenant_service.main:app --reload --port 8002
```
You should see `Uvicorn running on http://127.0.0.1:8002`.

---

## 6. Try it — candidate signup (simplest end-to-end path)

In a third terminal (or Postman/Insomnia if you prefer a GUI):

```powershell
# 1. Start signup
curl -X POST http://localhost:8001/signup/candidate `
  -H "Content-Type: application/json" `
  -d '{"email":"jane@example.com","full_name":"Jane Doe","password":"super-secret-123"}'
```

Look at **Terminal 2** (auth_service) — because `OTP_DEBUG_LOG_ENABLED=true`,
you'll see a log line like:
```
INFO auth_service.otp [DEV ONLY] OTP for jane@example.com (purpose=candidate_signup): 483920
```

```powershell
# 2. Verify with that code
curl -X POST http://localhost:8001/signup/candidate/verify-otp `
  -H "Content-Type: application/json" `
  -d '{"email":"jane@example.com","otp_code":"483920"}' `
  -c cookies.txt
```
(`-c cookies.txt` saves the httpOnly cookies curl received, so you can
reuse the session — check `cookies.txt`, you should see
`insynchire_access` and `insynchire_refresh`.)

```powershell
# 3. Log in again with the same credentials, just to prove login works too
curl -X POST http://localhost:8001/auth/login `
  -H "Content-Type: application/json" `
  -d '{"email":"jane@example.com","password":"super-secret-123"}'
```

---

## 7. Try it — company signup (exercises the Migration Service too)

```powershell
curl -X POST http://localhost:8001/signup/company `
  -H "Content-Type: application/json" `
  -d '{"company_name":"Acme Corp","subdomain":"acme","company_email":"founder@acme-corp.com","full_name":"Alice Founder","password":"super-secret-123"}'
```

**Note:** the domain validation step does a REAL MX-record DNS lookup —
`acme-corp.com` isn't a real domain, so this will fail with "does not
appear to be able to receive email". Use a domain you know has a real
mail server (e.g. your own company's domain, or something like
`microsoft.com` just to test the happy path) — just not one of the
blocked public providers (gmail.com, outlook.com, etc.).

Once that succeeds, grab the OTP from Terminal 2's logs the same way,
then:
```powershell
curl -X POST http://localhost:8001/signup/company/verify-otp `
  -H "Content-Type: application/json" `
  -d '{"company_email":"founder@yourrealdomain.com","otp_code":"XXXXXX"}'
```

Now watch **Terminal 1** (migration_service) — you should see it pick
up the `tenant.signup_initiated` event and log that it's provisioning
the tenant database. Confirm the new database actually exists:
```powershell
docker exec -it insynchire-pg psql -U postgres -c "\l" | findstr tenant
```

Then watch **Terminal 3** (tenant_service) — once Migration Service
finishes and publishes `tenant.created`, you should see a log line
like:
```
INFO tenant_service.main bootstrapping company_admin for tenant_id=...
```
That's Tenant Service creating the default Organization and assigning
your signup's user as `company_admin` — confirm it landed:
```powershell
docker exec -it insynchire-pg psql -U postgres -c "\l" | findstr tenant
REM grab the tenant_<hex>_db name from that list, then:
docker exec -it insynchire-pg psql -U postgres -d tenant_XXXXXXXX_db -c "SELECT * FROM tenant_user_memberships;"
```
You should see one row with `role = company_admin`.

---

## 8. Try it — invite a teammate (Tenant Service)

You need the `company_admin`'s session cookie from step 7 (the
`verify-otp` call saved it if you passed `-c cookies.txt` the same way
as the candidate flow — re-run that call with `-c cookies.txt` if you
skipped it).

```powershell
curl -X POST http://localhost:8002/tenant/invites `
  -H "Content-Type: application/json" `
  -b cookies.txt `
  -d '{"email":"newhire@yourrealdomain.com","role":"recruiter"}'
```

Watch **Terminal 3** — with `INVITE_DEBUG_LOG_ENABLED=true` you'll see:
```
INFO tenant_service.invite [DEV ONLY] invite token for newhire@yourrealdomain.com (tenant=acme, role=recruiter): <long-token>
```

The invited person doesn't have an account yet — they'd sign up as a
candidate first (step 6), then accept the invite as themselves:
```powershell
curl -X POST http://localhost:8002/tenant/invites/accept `
  -H "Content-Type: application/json" `
  -H "X-Tenant-Subdomain: acme" `
  -b newhire_cookies.txt `
  -c newhire_cookies.txt `
  -d '{"invite_token":"<paste-the-token-from-the-log>"}'
```
(`newhire_cookies.txt` should already contain that person's own
candidate-signup session cookie from step 6, captured the same way as
Jane's.) The response includes their new `role` and sets fresh cookies
scoped to this tenant.

**Selecting a tenant later** (e.g. after logging back in fresh, or if a
user belongs to multiple tenants): the same cookie-bearing user can
call:
```powershell
curl -X POST http://localhost:8002/tenant/select `
  -H "Content-Type: application/json" `
  -b newhire_cookies.txt -c newhire_cookies.txt `
  -d '{"subdomain":"acme"}'
```

---

## 9. Shutting down

```powershell
# Stop the three Python processes with Ctrl+C in their terminals, then:
docker stop insynchire-pg insynchire-redis insynchire-kafka
```
(Use `docker start ...` next time instead of `docker run` — the
containers and their data persist.)

---

## What's NOT wired up yet (expected gaps at this stage)

- **No real emails are sent.** `OTP_DEBUG_LOG_ENABLED` and
  `INVITE_DEBUG_LOG_ENABLED` are stopgaps until the Notification
  Service (M7) exists.
- **No `docker-compose.yml` yet** — that's Task P, once more services
  exist and a single-command startup is worth writing.
- **Role changes / promoting someone to `company_admin` after the
  fact** aren't built — the only path to `company_admin` is being the
  original tenant creator.
