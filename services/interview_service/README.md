# LOCATION: services/interview_service/README.md

# Interview Service (M8 — scheduling/join, + M9 — live WebSocket room)

FastAPI service owning `/interviews/*` HTTP routes (scheduling, invite-
triggering, join) and the `/ws/interviews/{session_id}` WebSocket
gateway (chat, collaborative code editor relay, agent event channel,
session state transitions). Follows the same repository-pattern /
`TenantResolver` conventions `job_service` and `tenant_service` already
established.

## HTTP routes (M8)

1. **Schedule** (`POST /interviews/schedule`, `company_admin`/`recruiter`
   only) — creates an `interview_sessions` row (status=`SCHEDULED`),
   mints and encrypts an opaque room token, and publishes
   `interview.scheduled` to Kafka. That topic and event schema already
   existed in `insynchire-events` before this milestone and are already
   consumed by two M7 services — Notification Service (sends the email)
   and `user_profile_service`'s `NotificationRecordConsumerService`
   (writes the in-app `user_notifications` row) — so scheduling here
   "just works" against that existing pipeline with **no changes needed
   on either consumer**.
2. **View** (`GET /interviews/{id}`, `company_admin`/`recruiter`/
   `interviewer`/`observer`) — `company_admin`/`recruiter` may view any
   session in their tenant; `interviewer`/`observer` may only view
   sessions they were actually assigned to (their `user_id` appears in
   `interviewer_ids`/`observer_ids`).
3. **Join** (`POST /interviews/{id}/join`, all five roles including
   `candidate`) — authorizes the caller against the session's actual
   assignment, records an idempotent `interview_participants` row, and
   returns TWO tokens (see M9 section below): the decrypted `room_token`
   and (M9) a fresh `ws_connect_token`. Candidates (whose tokens carry
   no tenant context at all) authenticate the same `X-Tenant-Id` header
   way `job_service`'s candidate apply/my-application routes already
   established.

## WebSocket gateway (M9)

`POST /interviews/{id}/join`'s response now also includes
`ws_connect_token` — a short-lived (5 min default), per-participant,
signed token (`ws_tokens.WSConnectTokenService`) the client passes as a
query parameter when opening the WebSocket connection:
ws://<host>/ws/interviews/{session_id}?token=<ws_connect_token>

This is a genuinely different token from `room_token` — see
`ws_tokens.py`'s module docstring: `room_token` is a future SFU/video
credential (same value for every participant), `ws_connect_token` is
THIS service's own gateway's per-participant handshake credential.

What the gateway does once connected:

- **Chat** — relayed to every other connection on the session;
  `observer` is read-only (a chat send from an observer is rejected).
- **Collaborative code editor** (`code_update`) — *** INTERIM
  IMPLEMENTATION ***, flagged explicitly in `ws_gateway.py`'s module
  docstring: a simplified whole-document relay (broadcasts the editor's
  full current content) rather than a real Yjs CRDT binary-protocol
  merge. Every update is persisted as the next `code_snapshots` row
  (migration `0006_code_snapshots`; Section 5: "full history with
  diffs — enables playback"). Real Yjs sync is a follow-up milestone.
- **Agent event channel** (`agent_event`) — the emission PLUMBING only:
  routed to `interviewer`-role connections exclusively (never
  candidate, never observer, matching Section: "Co-Pilot ... never
  emitted to candidate" / "Integrity ... interviewer only"). No agent
  actually runs yet — that's M10's LangGraph interview pipeline (Graph
  1). This just proves the routing is correct ahead of time.
- **Session state** — the first STAFF connection (never a lone
  candidate) transitions `SCHEDULED` → `IN_PROGRESS`; an `end_session`
  message (staff-only, `company_admin`/`recruiter`) transitions to
  `COMPLETED` and publishes `interview.completed` (the topic/schema
  already existed in `insynchire-events`).

### Explicit, documented gap: Redis pub/sub

The Tech Stack section calls for "Redis Pub/Sub: WebSocket message
broker across multiple FastAPI instances." `broadcaster.py`'s
`InProcessBroadcaster` only fans out within the CURRENT PROCESS's
connections — correct for a single instance, NOT correct once this
service is horizontally scaled. The module docstring spells out the
drop-in replacement path (publish to an `interview:{session_id}` Redis
channel, every instance subscribes and fans out locally) — not
implemented in M9, flagged rather than silently deferred.

## What this milestone still does NOT include

No real Yjs CRDT merge semantics (see above), no video/voice SFU
integration (Section 10f), no LangGraph interview pipeline graph
(Graph 1, M10). `room_token` is still an opaque identifier, not yet a
genuine per-participant SFU (LiveKit/Daily/Twilio) token (see
`crypto.py`'s module docstring).

## New tenant-DB tables

- **M8** — `interview_sessions`, `interview_participants` (migration
  `0005_interview_sessions`).
- **M9** — `code_snapshots` (migration `0006_code_snapshots`).

Both migrations extend the SAME tenant Alembic chain Migration Service
owns and runs on every new tenant provisioning — not a second chain.
Existing tenants need these applied via the system-admin
`migrate-all-tenants` CLI command. Every table carries RLS + an
explicit `tenant_id` column, same precedent
`0004_job_openings_and_applications` established.

## Install

```bash
cd insynchire
pip install -e shared/insynchire-events
pip install -e shared/shared-db
pip install -e shared/auth-tokens
pip install -e shared/permissions
pip install -e "services/interview_service[dev]"
```

## Run the tests (no Postgres/Redis/Kafka required)

```bash
cd services/interview_service
python -m pytest -q
```

Expected: `32 passed` (17 from M8 + 15 from M9: 5 `ws_tokens` unit
tests, 10 `ws_gateway` integration tests).

**What's genuinely exercised, not mocked:** the encrypt-then-connect
tenant DB resolution (`TenantResolver`), the room-token AND
ws-connect-token encrypt/decrypt round trips, all run against real
(temp-file SQLite / real Fernet) implementations, not stand-ins.
`test_routes_integration.py` drives the actual FastAPI app via httpx's
ASGI transport through the full schedule → view → join HTTP flow for
five different roles. `test_ws_gateway_integration.py` drives a REAL
running Uvicorn server (see "Testing note" below) through the full
connect → chat → code_update → agent_event → end_session flow across
multiple simultaneous real WebSocket connections, including the
authorization-denial paths (observer can't chat, can't end_session;
unassigned staff can't view/join) and cross-role event isolation
(agent_event never reaches candidate/observer).

**What still needs a real check before deploying:** actual Postgres RLS
enforcement (SQLite can't test that) and real Kafka delivery of
`interview.scheduled`/`interview.completed` end to end into the
already-built Notification Service / `user_profile_service` consumers.

### Testing note: why the WebSocket tests use a real Uvicorn server, not `TestClient`

Every other integration test in this repo uses `httpx.ASGITransport`
or Starlette's `TestClient` in-process. For this gateway specifically,
that's unsafe: `TestClient.websocket_connect()` runs each connection in
its own isolated background thread + event loop, and this gateway's
core job (cross-connection broadcast + per-message tenant DB access)
deadlocks across two such isolated connections — a coroutine awaiting a
SQLAlchemy async-engine operation whose underlying `aiosqlite`
primitives were first bound to a DIFFERENT connection's event loop
never resolves. `test_ws_gateway_integration.py`'s module docstring
explains this in full and the fix actually used: a real Uvicorn server
in a background thread (Kafka lifespan disabled via `lifespan="off"`,
so no real broker is needed), driven by the `websockets` client library
over a real TCP socket — the same shape a real browser client uses,
and the same shared-event-loop behavior this service has in actual
production, where cross-connection broadcast and per-connection DB
access both work correctly.

## Configuration gotchas

- `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH` / `TOKEN_PAYLOAD_ENCRYPTION_KEY`
  **must be identical** to Auth Service's — this service only verifies
  tokens, it never issues its own.
- `CONNECTION_STRING_ENCRYPTION_KEY` **must be identical** to Migration
  Service's — otherwise this service can't decrypt tenant connection
  strings Migration Service encrypted.
- `ROOM_TOKEN_ENCRYPTION_KEY` is a **separate, dedicated** key — do NOT
  reuse `CONNECTION_STRING_ENCRYPTION_KEY` for it (see `crypto.py`'s
  module docstring for why). Generate it the same way:
```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
- `WS_CONNECT_TOKEN_TTL_SECONDS` (M9, default 300) controls how long a
  `ws_connect_token` stays valid after `/join` issues it — a client
  that waits too long to open the WebSocket after joining will need to
  call `/join` again.

## Folder contents
```
services/interview_service/
├── pyproject.toml
├── .env.example
├── README.md
├── interview_service/
│ ├── init.py
│ ├── config.py
│ ├── crypto.py ← RoomTokenCrypto (dedicated key, see docstring)
│ ├── ws_tokens.py (M9) ← WSConnectTokenService: short-lived per-participant handshake token
│ ├── connection_manager.py (M9) ← SessionConnectionRegistry: in-process live-connection tracking
│ ├── broadcaster.py (M9) ← InProcessBroadcaster (interim -- see docstring re: Redis pub/sub gap)
│ ├── ws_gateway.py (M9) ← the WebSocket route + message handlers
│ ├── auth_dependency.py ← staff matrix enforcement + dual staff/candidate join resolution
│ ├── dependencies.py
│ ├── main.py
│ ├── tenant_db.py ← TenantResolver: decrypt + connect + RLS activate
│ ├── models/ ← Tenant/GlobalUser (global, read-only) + InterviewSession/InterviewParticipant/CodeSnapshot (tenant DB)
│ ├── schemas/
│ ├── repositories/
│ │ └── code_snapshot_repository.py (M9)
│ ├── services/
│ │ ├── scheduling_service.py ← schedule_interview, get_session_for_staff
│ │ └── join_service.py ← join (authorization + participant record + room_token + ws_connect_token)
│ └── routes/
│ └── interview_routes.py
└── tests/
├── conftest.py
├── test_scheduling_service.py
├── test_join_service.py
├── test_routes_integration.py
├── test_ws_tokens.py (M9)
└── test_ws_gateway_integration.py (M9)
```

## Known gap flagged, not silently worked around

`AgentIntegrityFlaggedEvent` (FIX-M0) still has no `interviewer_ids`
field — M7's Notification Service documented this as a loud, logged
no-op. `interview_participants` (M8) is queryable by `session_id` →
every participant + their `role_in_session`, which is exactly the data
a future fix would need to resolve that gap (look up
`interview_participants` where `role_in_session='interviewer'` for the
flagged `session_id`), but wiring that read path into Notification
Service remains out of scope here — flagged per the working
conventions rather than silently addressed or ignored.