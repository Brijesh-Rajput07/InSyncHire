# LOCATION: services/notification_service/README.md

# Notification Service (M7)

Headless service — **no HTTP routes** (Section 3: "Notification
Service (Kafka consumer only)"). Consumes every notification-relevant
topic named in Task N and sends email.

## What it does

Subscribes to 7 topics, each routed to a `NotificationDispatchService`
handler:

| Topic | Recipient(s) | How resolved |
|---|---|---|
| `user.invited` | the invitee | `email` field is directly on the event |
| `application.submitted` | every `company_admin`/`recruiter` in the tenant | tenant DB membership read |
| `candidate.advanced` | the candidate | `global_users` lookup by `candidate_user_id` |
| `candidate.rejected` | the candidate | `global_users` lookup by `candidate_user_id` |
| `interview.scheduled` | candidate + every interviewer | `global_users` lookup by `candidate_user_id` + `interviewer_ids` |
| `scorecard.generated` | every `company_admin`/`recruiter` in the tenant | tenant DB membership read |
| `agent.integrity_flagged` | *(none yet — see Known gap below)* | — |

Email is sent via a pluggable `EmailSender`: `ConsoleEmailSender`
(default, DEV/TEST ONLY — logs instead of sending, same stopgap
pattern as `OTP_DEBUG_LOG_ENABLED`) or `SendGridEmailSender` (the real
Section-3-named provider, lazy-imports the `sendgrid` package so it's
never required just to run the test suite).

## DB ownership — a precedent conflict, and how it's resolved

Section 3 literally says Notification Service "writes in-app
notifications to `users_db`." Following that literally would
reintroduce exactly the anti-pattern **FIX-M2** removed (a service
writing directly to a database another service owns) — `users_db` is
owned by `user_profile_service` (M4), and **M5** already established
the fix for this exact situation: when a different service needs a row
written to `users_db`, it publishes the event and `user_profile_service`
(the owner) consumes it and does the write itself (see M5's
`ApplicationSubmittedConsumerService` → `user_applications_index`).

This milestone follows that same precedent:

- **Notification Service** (this package) does **only** the email half
  of Section 3's description. It touches no database it doesn't own —
  its only "write" is an outbound email. Reading `insynchire_global`
  and a tenant DB to *resolve recipients* is a read, not a write, and
  is the same sanctioned read pattern `tenant_service`/`job_service`
  already use for their own cross-database context.
- **`user_profile_service`** gained a **new consumer**,
  `NotificationRecordConsumerService`, which independently subscribes
  to the candidate-identifiable topics (`candidate.advanced`,
  `candidate.rejected`, `interview.scheduled`) and writes the
  `users_db.user_notifications` row itself — see that service's own
  changes for this milestone.

**Scope note:** `NotificationRecordConsumerService` does NOT yet write
rows for `application.submitted`/`scorecard.generated` (would require
`user_profile_service` to also gain a `TenantResolver`, duplicating
this service's tenant-membership-reading capability) or
`agent.integrity_flagged` (blocked on the same missing
`interviewer_ids` gap described below). Both are called out explicitly
in that service's new module's docstring as a deliberate, documented
boundary — not a silently-dropped requirement.

## Known gap — `agent.integrity_flagged`

Section 3 says this event should alert "the interviewer", but
`AgentIntegrityFlaggedEvent` (FIX-M0) carries only `tenant_id`/
`session_id`/`signal_type`/`confidence_score` — no `interviewer_ids`.
Resolving the actual interviewer(s) needs `interview_sessions`, a
tenant-DB table that doesn't exist until Interview Service (M8). Until
then, `handle_agent_integrity_flagged` logs a **WARNING** (visible in
ops output) and sends nothing — a loud, documented no-op is safer than
either silently dropping the event or guessing a recipient. Revisit
once M8 either extends the event with `interviewer_ids` or this
service gains a read path to `interview_sessions`.

## Install

```bash
cd insynchire
pip install -e shared/insynchire-events
pip install -e shared/shared-db
pip install -e "services/notification_service[dev]"
```

## Run the tests (no Postgres/Redis/Kafka required)

```bash
cd services/notification_service
python -m pytest -q
```

Expected: `20 passed`.

**What's genuinely exercised, not mocked:** the recruiter/company_admin
tenant-membership resolution (`_get_recruiter_emails`) and the job-title
lookup (`_get_job_title`) run against a REAL temp-file SQLite tenant DB
with a real encrypted connection string — the same "genuinely exercise
the decrypt-then-connect path" philosophy `tenant_service`'s and
`job_service`'s test suites already use. `ConsoleEmailSender` records
every message actually "sent" so tests assert on real recipient lists,
not a mocked call.

## Running the service for real

```bash
uvicorn — not applicable, this service has no HTTP server.
python -m notification_service.main serve
```

## Configuration gotchas

- `CONNECTION_STRING_ENCRYPTION_KEY` **must be identical** to Migration
  Service's — otherwise this service can't decrypt tenant connection
  strings Migration Service encrypted, and recruiter/company_admin
  resolution for `application.submitted`/`scorecard.generated` will
  silently resolve to zero recipients (logged as a warning, never a crash).
- `EMAIL_PROVIDER=console` is the default and is **DEV/TEST ONLY** —
  never leave it set in a real deployment. Switch to
  `EMAIL_PROVIDER=sendgrid` and set `SENDGRID_API_KEY` for real sending.

## Folder contents

```
services/notification_service/
├── pyproject.toml
├── .env.example
├── README.md
├── notification_service/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py                          ← headless entrypoint, 7 topic subscriptions
│   ├── dependencies.py                  ← plain factory wiring (no FastAPI DI -- no routes)
│   ├── tenant_db.py                     ← TenantResolver (read-only)
│   ├── models/
│   │   ├── base.py
│   │   ├── global_models.py             ← Tenant, GlobalUser (read-only mirrors)
│   │   └── tenant_models.py             ← TenantUserMembership, JobOpening (read-only mirrors)
│   ├── repositories/
│   │   ├── global_tenant_repository.py
│   │   ├── global_user_repository.py
│   │   ├── membership_repository.py
│   │   └── job_opening_repository.py
│   ├── email/
│   │   ├── email_sender.py              ← EmailSender protocol, ConsoleEmailSender, SendGridEmailSender
│   │   └── templates.py                 ← subject/body builders per event
│   └── services/
│       └── notification_dispatch_service.py  ← one handle_* method per topic
└── tests/
    ├── conftest.py
    ├── test_email_sender.py
    ├── test_templates.py
    └── test_notification_dispatch_service.py
```