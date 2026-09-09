# InSyncHire — Master Project Plan (Updated through M10 Slice 2)

*Paste this whole document (or at minimum Section 1) into a new agent
session whenever you want help building any part of this project. It
contains full context, architecture decisions, guardrails, security
rules, and current build status. Task-by-task build/verify prompts now
live in the companion file `PHASE_PROMPTS.md` — use that alongside this
one.*

---

## 0. How to use this document (and its companion, PHASE_PROMPTS.md)

1. Upload **both** `PROJECT_PLAN.md` (this file) and `PHASE_PROMPTS.md`
   into the coding agent's project/workspace.
2. Paste the **Context Block** (Section 1) at the start of a new
   session so the agent understands the whole system before touching
   any one phase.
3. Open `PHASE_PROMPTS.md`, find the next `🔲 NOT YET BUILT` phase, and
   paste **only that phase's Build prompt** — never more than one
   phase per session turn.
4. **Security (Section 10) and Guardrails (Section 1 — GUARDRAILS
   ARCHITECTURE) are not separate phases.** They apply to every module
   as it's built.
5. **Architecture decisions (Section 2) are already made** — do not
   re-open them without a documented, explicit reason.
6. After a phase is built, **make the agent run that phase's exact
   Verify commands from PHASE_PROMPTS.md and paste you the real output**
   before you say "proceed" to the next phase. Do not let it
   self-report success without pasted command output.
7. **Current status (this document's whole reason for existing):**
   M0 through M9 are built and were verified against the real repo
   in earlier sessions (test counts below, from each service's own
   README — treat these as ground truth). **M10 is split into 3
   slices**: Slice 1 (Graph 1 built, agent_service-only) and Slice 2
   (WebSocket gateway wired to Graph 1) were built and tested in an
   **isolated scratch sandbox**, not against your actual repository's
   full M8/M9 fixture files — see Section 13 for why this matters and
   what Phase 0 (below) does about it. Slice 3
   (`agent_decision_logs`/`agent_guardrail_logs` persistence), M11
   (real Report Synthesis + scorecard workflow), and everything from
   M12 onward are **not yet built**.

---

## 1. Context Block (paste this at the start of every chat)

```
PROJECT: InSyncHire
Type: Multi-tenant SaaS — AI-powered end-to-end technical hiring platform.

STATUS (see Section 4 for the authoritative table):
  M0–M9:              BUILT + VERIFIED against the real repo.
  M10 Slice 1 (Graph 1 in agent_service):        BUILT, needs re-verification
                                                   against the real repo (see Phase 0).
  M10 Slice 2 (WS gateway wired to Graph 1):     BUILT, needs re-verification
                                                   against the real repo (see Phase 0).
  M10 Slice 3 (agent_decision_logs/agent_guardrail_logs persistence): NOT BUILT.
  FIX-M9 (chat_messages table, optional):        NOT BUILT — needs explicit go-ahead.
  M11 (real Report Synthesis + scorecard workflow + PDF):             NOT BUILT.
  M12 (Reporting Service + system admin dashboard):                   NOT BUILT.
  M13 (Observability: LangSmith, evals, load testing, security audit): NOT BUILT.
  Task Q (docker-compose.yml):                                        NOT BUILT.
  Angular frontend (Section 7, all of it):                            NOT BUILT.

PRODUCT VISION:
InSyncHire is a real SaaS product. Companies sign up as tenants and use
InSyncHire as their entire technical hiring layer: posting jobs,
receiving applications, AI-ranking candidates, scheduling interviews,
running live collaborative coding interviews with AI agents assisting
interviewers in real time, and generating structured evidence-based
scorecards. Candidates have a global profile and can apply to any
company on the platform.

No comparable end-to-end product currently exists. The differentiator is:
full hiring pipeline + coordinated multi-agent AI with proper guardrails +
isolated multi-tenant architecture with enterprise-grade security.

═══════════════════════════════════════════════════════════════
MULTI-TENANT ARCHITECTURE
═══════════════════════════════════════════════════════════════

DATABASE MODEL — 4 separate databases:

1. insynchire_global (control plane DB)
   - tenants: tenant_id (uuid PK), subdomain, company_name, company_domain,
     db_connection_string (AES-256 encrypted), plan, status (PENDING/ACTIVE/
     SUSPENDED), created_at, suspended_at, suspended_reason, created_by_user_id
   - tenant_migrations: tenant_id (FK), alembic_version, applied_at,
     applied_by_service — Migration Service reads this for pending migrations
   - global_users: user_id (uuid PK), email (unique), password_hash, full_name,
     phone, avatar_url, is_active, is_email_verified, created_at, last_login_at,
     account_type (candidate | company_user)
   - No RLS needed — access always via authenticated service code with explicit scope

2. reporting_db (system admin read DB — Kafka-fed ONLY, never written by services)
   - tenant_stats, user_stats, job_stats, interview_stats, agent_stats
   - error_logs, guardrail_logs, audit_trail, kafka_consumer_lag
   - NOT BUILT YET (M12). ONLY Reporting Service will write here.

3. tenant_{tenant_id}_db (one per tenant — full RLS isolation)
   - Created by Migration Service on tenant signup.
   - PostgreSQL RLS on every table: SET app.current_tenant_id at session start.
   - Tables that EXIST as of this document (tenant Alembic chain,
     6 revisions applied so far):
     0001_initial:        organizations, tenant_user_memberships
     0002_invited_users:  invited_users
     0003_agent_and_process_logs: agent_decision_logs, agent_guardrail_logs, process_logs
     0004_job_openings_and_applications: job_openings, job_applications
     0005_interview_sessions: interview_sessions, interview_participants
     0006_code_snapshots: code_snapshots
   - Tables still MISSING that later milestones need:
     question_bank (pgvector, needed for a real rag_question_retrieval_tool),
     scorecards, scorecard_approvals (needed for M11),
     chat_messages (needed for a real fetch_session_transcript_tool — see
     FIX-M9 in Section 4, optional, not yet approved to build).

4. users_db (global user extended profile DB — no tenant data)
   - user_profiles, user_resumes, user_applications_index,
     user_interview_history, user_notifications. All BUILT (M4/M5/M7).

CONNECTION ROUTING MIDDLEWARE (every authenticated request):
  1. Read encrypted httpOnly cookie → AES-256 decrypt → extract
     {user_id, tenant_id, org_id, role, session_fingerprint, issued_at}
  2. Check token not in Redis denylist (revoked tokens)
  3. Validate session_fingerprint = hash(current IP + current UA) — detects theft
  4. Connect to insynchire_global → verify tenant ACTIVE, not SUSPENDED
  5. Fetch tenant's encrypted DB connection string → decrypt → get PgBouncer
     pooled connection for that tenant's DB (pool cached in Redis by tenant_id)
  6. SET app.current_tenant_id on the DB session (activates RLS)
  7. Validate user role has permission for this specific endpoint + HTTP method
  8. Inject {tenant_id, org_id, user_id, db_conn, role, trace_id} into request state
  9. Pass to route handler
  Skipped for: /auth/*, /signup/*, /public/jobs, /health, /webhooks/*
  NOTE: no single shared middleware module exists yet — every service
  builds its own scoped-down `TenantResolver` (Section 6). Extracting a
  real shared connection-routing middleware is still a documented,
  deferred piece of future work (each service's own README says so).

TOKEN / SESSION SECURITY:
  - httpOnly + Secure + SameSite=Strict cookies only — never localStorage
  - Payload AES-256 encrypted before RS256 JWT signing — decoded JWT = ciphertext
  - Access token: 15 min TTL. Refresh token: 7 days, rotated on every use.
  - Redis denylist: logout / role change / tenant suspension = immediate revocation
  - session_fingerprint: hash(IP + User-Agent) embedded in token, re-checked
    on every request — token stolen from a different device/IP is rejected
    (FIX-M2, genuinely enforced, not just embedded-and-ignored).

TENANT ONBOARDING FLOW:
  1. Company registers → corporate domain validation:
     a. Blocklist check: gmail/outlook/yahoo/hotmail/protonmail/icloud + ~40 others
     b. MX record DNS lookup: confirms domain actually receives email
     c. OTP sent to submitted corporate email address
     d. Max 3 OTP attempts, then 15-min lockout
  2. OTP verified → insynchire_global.tenants created (status=PENDING)
     → Kafka: tenant.signup_initiated
  3. Migration Service consumes → provisions tenant_{id}_db → runs full Alembic
     migration suite → updates tenant_migrations → sets tenant status=ACTIVE
     → Kafka: tenant.created
  4. First company user auto-assigned company_admin in tenant_user_memberships
  5. company_admin invites team via email (validated against tenant's domain only)
     → assigned role at invite time: recruiter / interviewer / observer

CANDIDATE ONBOARDING FLOW:
  - Any email accepted (no domain restriction)
  - OTP verification → global_users record created by Auth Service, then
    Auth Service publishes user.registered → User Profile Service (M4)
    consumes it and creates users_db.user_profiles (FIX-M2: Auth Service
    itself never writes users_db directly)
  - No tenant DB touched until they apply to a job or join an interview room

═══════════════════════════════════════════════════════════════
MICROSERVICES & KAFKA EVENT ARCHITECTURE
═══════════════════════════════════════════════════════════════

SERVICES (status noted):

1. Auth Service (API Gateway) — BUILT (M2)
   - /auth/* and /signup/* routes. Cookie issuance, token validation,
     OTP, domain validation. No business logic beyond auth.

2. Tenant Service — BUILT (M3)
   - Tenant config, org settings, user memberships, role assignments.
   - Domain-scoped invite flow, invite acceptance (410/409/428 status
     codes), tenant selection.

3. Migration Service — BUILT (M1), headless, no HTTP routes
   - Kafka consumer: tenant.signup_initiated → provisions tenant DB.
   - CLI: `migrate-all-tenants` (alias `migrate-all`) — system_admin only.

4. User Profile Service — BUILT (M4/M5/M7)
   - Owns users_db. Consumes user.registered → creates user_profiles.
   - /profile + /profile/resume endpoints (candidate-only via
     account_type check, since candidate tokens always carry role=None).
   - M5 addition: consumes application.submitted → user_applications_index.
   - M7 addition: consumes candidate.advanced/rejected/interview.scheduled
     → writes in-app user_notifications (Notification Service handles
     the EMAIL half only — see the M7 DB-ownership precedent below).

5. Job Service — BUILT (M5)
   - Job postings CRUD (recruiter/company_admin).
   - Application submission (tenant DB + publishes application.submitted).
   - Interim /public/jobs board (documented stopgap — scans every ACTIVE
     tenant DB directly; replace with a real reporting_db aggregate once
     M12 exists).
   - AI Ranking Agent trigger point NOT wired yet (Graph 2 exists in
     Agent Service but nothing calls RankingAgentService from Job
     Service yet — flagged gap, not yet a phase).

6. Interview Service — BUILT (M8/M9), extended in M10 Slice 2
   - M8: /interviews/schedule, /interviews/{id} GET, /interviews/{id}/join.
   - M9: /ws/interviews/{session_id} WebSocket gateway — chat (role-gated),
     interim whole-document code editor relay + code_snapshots persistence,
     session state transitions, agent_event plumbing (interviewer-only).
   - M10 Slice 2: the agent_event plumbing is now REAL — code_update
     triggers (debounced) Graph 1's code_analysis_node + copilot_node;
     new message types integrity_event / question_request /
     phase_transition_request / human_decision drive the rest of Graph 1.
     See Section 13 for the AgentBridge design and its flagged gaps.

7. Agent Service (dedicated) — BUILT (M6, M10 Slice 1)
   - Owns GuardrailService (all 5 layers) — BUILT, unit-tested, no live
     LLM dependency required to test it.
   - Owns GRAPH 2 (AI Ranking Agent) — BUILT (M6): real LangGraph,
     genuine interrupt/resume, rule-based scorer, interim RAG stand-in.
   - Owns GRAPH 1 (interview pipeline) — BUILT (M10 Slice 1): all named
     nodes, all 3 human-in-the-loop interrupts genuinely proven, all
     named tools (some mocked/interim/gap-flagged — see Section 13).
   - Still has NO HTTP surface (Section 6 always said "no routes" for
     this service) — Interview Service calls it in-process via
     `agent_bridge.py` (an explicit architectural decision, Section 13).
   - agent_decision_logs / agent_guardrail_logs persistence to a real
     tenant DB: NOT BUILT (M10 Slice 3). GuardrailService.logged_events
     is still in-process-only.

8. Notification Service — BUILT (M7), headless, no HTTP routes
   - Consumes 7 topics, sends EMAIL only (pluggable EmailSender,
     console/SendGrid). Does NOT write any database it doesn't own
     (see the M7 DB-ownership precedent: in-app notification rows are
     written by User Profile Service instead, which owns users_db).
   - Known gap: agent.integrity_flagged has no resolvable recipient
     (AgentIntegrityFlaggedEvent carries no interviewer_ids) — logs a
     loud WARNING, sends nothing. Same gap noted in M7 and unchanged.

9. Reporting Service — NOT BUILT (M12).

10. insynchire-events (internal shared Python package) — BUILT (M0)
    - Pydantic v2 models for every Kafka event schema, publish/subscribe
      with retry + DLQ. Includes all 6 agent.* topics + GuardrailEvent
      (FIX-M0).

KAFKA TOPICS: unchanged from the original architecture — see Section 5
of the original doc if you need the full table; every topic listed
there is registered in `insynchire_events.topics.Topics` and has a
schema in `EVENT_SCHEMA_REGISTRY`. Nothing new was added in M6–M10.

═══════════════════════════════════════════════════════════════
FULL HIRING PIPELINE FLOW (Stages 1–7) — status per stage
═══════════════════════════════════════════════════════════════

STAGE 1 — JOB POSTING: BUILT (Job Service, M5).
STAGE 2 — APPLICATION: BUILT (Job Service, M5).
STAGE 3 — AI RANKING: Graph 2 BUILT (M6) but NOT WIRED — Job Service
  does not call RankingAgentService anywhere yet. Flagged gap.
STAGE 4 — SHORTLISTING: BUILT (Job Service, M5 — advance/reject).
STAGE 5 — INTERVIEW SCHEDULING: BUILT (Interview Service, M8).
STAGE 6 — LIVE INTERVIEW ROOM: Chat/code-editor/session-state BUILT
  (M9). Agent pipeline (Graph 1) now genuinely wired (M10 Slice 2) for
  code analysis / Co-Pilot / integrity / question suggestion / phase
  transitions. Video/voice (WebRTC/SFU) NOT BUILT at all.
STAGE 7 — POST-INTERVIEW: NOT BUILT for real (M11). `end_session`
  (M9) marks the session COMPLETED and publishes interview.completed,
  but deliberately does NOT trigger Graph 1's report_synthesis_node —
  see Section 13 for why.

═══════════════════════════════════════════════════════════════
ROLE HIERARCHY (server-enforced — never trust client) — UNCHANGED
═══════════════════════════════════════════════════════════════

GLOBAL: system_admin — manually provisioned only, no self-serve path.
TENANT SCOPE: company_admin, recruiter, interviewer, observer.
GLOBAL CANDIDATE: candidate — global token always carries role=None;
  every service that needs "is this caller a candidate" checks
  account_type via a read-only global_users lookup instead (this
  pattern repeats in user_profile_service, job_service,
  interview_service — documented in each service's auth_dependency.py).

RBAC ENFORCEMENT: unchanged — checked server-side on every endpoint and
every WebSocket message type. `shared/permissions`'s PERMISSION_MATRIX
(FIX-M3) is the single source of truth for HTTP routes; WebSocket
message-type authorization is enforced ad hoc per gateway (Interview
Service's ws_gateway.py has its own AGENT_CONTROL_ALLOWED_ROLES /
SESSION_END_ALLOWED_ROLES sets — these are NOT in PERMISSION_MATRIX,
since that matrix only covers HTTP routes per its own docstring).

═══════════════════════════════════════════════════════════════
AGENTIC AI WORKFLOW (LangGraph) — CURRENT STATUS
═══════════════════════════════════════════════════════════════

FRAMEWORK: LangGraph, real `StateGraph` + `MemorySaver` checkpointer,
genuine `interrupt_before` pauses. Both graphs use `thread_id` = the
relevant session/job identifier so state persists across separate
`.ainvoke()` calls — this is the actual working pattern in this
codebase, not a future aspiration.

GRAPH 2 — AI RANKING AGENT: BUILT (M6). See
`services/agent_service/agent_service/graphs/ranking_graph.py`.
NOT WIRED to Job Service yet (Stage 3 gap above).

GRAPH 1 — INTERVIEW PIPELINE GRAPH: BUILT (M10 Slice 1). See
`services/agent_service/agent_service/graphs/interview_graph.py`.
**Key documented architectural decision**: this graph is invoked ONCE
PER INCOMING EVENT (a WebSocket message), not as one long-running call
that loops internally — see that file's module docstring for the full
reasoning. Nodes the original plan described as "routing back to
orchestrator_node" are terminal for that invocation; the NEXT real-world
event drives the next `.ainvoke()` against the same `thread_id` (the
interview `session_id`).

All 3 human-in-the-loop interrupts are real and independently proven:
  1. Question approval — `human_approval_node` (approval_type=QUESTION)
  2. Scorecard approval — `human_approval_node` (approval_type=SCORECARD)
  3. Phase transition confirmation — `phase_transition_node`

A 4th signal exists but is NOT a graph pause: exceeding the integrity
escalation threshold (Rule 5.4) sets `awaiting_human_approval=True,
human_approval_type="INTEGRITY_REVIEW"` as an OUTPUT SIGNAL ONLY —
`integrity_node` routes straight to `END`. The interviewer's actual
decision (continue or end the session) goes through the EXISTING
`end_session` WebSocket message (M9), not a graph resume. This was a
real bug caught during M10 Slice 1 testing (the flag had no route to
`human_approval_node` and would have gone permanently stale) — fixed by
having `orchestrator_node` clear it at the start of the next invocation.

TOOLS (Graph 1) — status per tool:
| Tool | Status |
|---|---|
| `run_in_sandbox` | **MOCKED, flagged.** Never executes candidate code (Section 10a). |
| `analyze_complexity` | Real, rule-based (no LLM). |
| `calibrate_difficulty` | Real, rule-based (no LLM). |
| `retrieve_candidate_questions` | **Interim.** In-memory Jaccard stand-in for a real pgvector `question_bank` search (table doesn't exist yet). |
| `build_code_history_summary` | Real formatter; the actual DB read stays in Interview Service's own `CodeSnapshotRepository` (repository pattern preserved). |
| `fetch_session_transcript` | **Gap flagged, not faked.** Always `available=False` — no `chat_messages` table exists (see FIX-M9 in Section 4). |

TOOLS (Graph 2, unchanged from M6): `profile_scorer_tool` (real,
rule-based), `rag_job_similarity_tool` (interim Jaccard stand-in for
pgvector).

AGENT MEMORY STRATEGY: SHORT-TERM (in-session) is real — LangGraph's
`MemorySaver` checkpointer, keyed by session_id/job_id. LONG-TERM
(cross-session RAG via `question_bank` pgvector embeddings) does NOT
exist yet — every "RAG" tool in this codebase is an interim in-memory
stand-in, clearly labeled, with a documented migration path to a real
pgvector query behind the exact same function signature.

═══════════════════════════════════════════════════════════════
GUARDRAILS ARCHITECTURE (5 layers) — BUILT, M6
═══════════════════════════════════════════════════════════════

All 5 layers (input/output/bias/PII/behavioral) are implemented,
unit-tested, and reused by BOTH Graph 1 and Graph 2 via the shared
`run_guarded_agent_node` wrapper (Section 11's pseudocode, concretely
implemented in `agent_service/guardrails/guardrail_service.py`).
Persistence of every guardrail check to `agent_decision_logs`/
`agent_guardrail_logs` (a real tenant DB write) is NOT built — M10
Slice 3. `GuardrailService.logged_events` is in-process only; Kafka
publish to `agent.guardrail_triggered` DOES work when a `publish`
callable is supplied (Interview Service's `AgentBridge` does not
currently supply one — another Slice 3 loose end to close).

NeMo Guardrails: still a config skeleton only (`colang/`), not a live
dependency — same status as M6 left it.

═══════════════════════════════════════════════════════════════
TECH STACK — status notes only where it differs from originally planned
═══════════════════════════════════════════════════════════════

Everything in the original tech stack section is unchanged EXCEPT:
- No real LLM provider (Anthropic/OpenAI/etc.) is wired in anywhere in
  this codebase. Every LLM-calling function in Agent Service is either
  a test double (agent_service's own test suites) or a clearly-labeled
  placeholder (`interview_service/agent_bridge.py`'s three
  `_placeholder_*_llm_call` functions). Wiring a real provider is
  explicitly scoped future work — see Section 13 and Phase 15/16 in
  PHASE_PROMPTS.md.
- No docker-compose.yml exists yet (Task Q, not started). Local dev
  still means `docker run` by hand per `LOCAL_APP_SETUP.md`.
- No Angular frontend code exists at all. Every milestone so far is
  backend-only.
- Code execution sandbox (Piston/Judge0): NOT wired in.
  `run_in_sandbox` is mocked, per Section 10a's own caution about this
  specific operation needing extra review before being built for real.

═══════════════════════════════════════════════════════════════
SECURITY POSTURE — unchanged, still applies to every new module
═══════════════════════════════════════════════════════════════

See the original Section 10 in full (all 9 subsections still apply
verbatim: candidate input untrusted, never exec/eval candidate code,
server-side auth on every endpoint AND every WebSocket event, RLS +
repository tenant scoping (two independent layers), httpOnly cookies
only, no secrets in code, every guardrail trigger logged, system_admin
manual-only, and the per-subsystem detail in 10a–10i). Nothing in
M6–M10 changed any of these rules — Graph 1's `run_in_sandbox` mock
exists specifically BECAUSE of Section 10a's caution, not despite it.

---

## 2. Architecture decisions (locked — do not re-open)

Same table as the original plan, PLUS these decisions made during
M6–M10 (added, not replacing anything):

| Decision | Choice | Why |
|---|---|---|
| (all original rows unchanged — repository pattern, RLS, Kafka, etc.) | | |
| Graph 1 invocation model | One `.ainvoke()` per incoming WebSocket event, `thread_id`=session_id | Matches how a real interview actually happens (discrete, unpredictably-timed events), and matches LangGraph's own checkpoint/resume design |
| Interview Service ↔ Agent Service calling convention | In-process Python import (`agent_bridge.py`), NOT HTTP | Agent Service has no HTTP surface yet; standing one up is its own decision, not a side effect of wiring the WS gateway. `agent_bridge.py` is the ONLY seam that would need to change if this becomes an HTTP call later |
| Sandbox execution tool | Mocked, deterministic, clearly labeled `mocked=True` | Section 10a requires extra caution specifically for code execution; wiring a real Piston/Judge0 sandbox needs its own explicit review, not a silent side effect |
| Integrity escalation (Rule 5.4) | Output signal only, NOT a graph interrupt | The interviewer's decision goes through the session's EXISTING `end_session` control, not a new graph pause — avoids a redundant, confusing second "end the session?" mechanism |
| `report_synthesis_node` / scorecard workflow | Deliberately NOT triggered by `end_session` yet | Full wiring (scorecard approval UX, `scorecard.generated` publish, PDF export) is M11's explicit job; firing it now with only a placeholder LLM would produce a scorecard that looks real but isn't |

---

## 3. Feature gap analysis (updated)

**Built since the original gap analysis:** everything in M4–M10 Slice 2
(see Section 4). **Still genuinely missing** (not a deliberate
non-goal, unlike the original doc's "deliberately not copied" list):

- AI Ranking Agent (Graph 2) is built but never called from Job Service.
- Real LLM provider — every "AI" output today is either a test double
  or a placeholder.
- Video/voice (WebRTC/SFU) — nothing built.
- Real Yjs CRDT sync — M9's code editor relay is whole-document,
  last-write-wins, not true CRDT merge.
- `question_bank`/pgvector — every "RAG" tool is an interim stand-in.
- Chat persistence — `chat_messages` table doesn't exist (FIX-M9).
- Reporting Service / system admin dashboard — M12, not started.
- Docker Compose / one-command local startup — Task Q, not started.
- Angular frontend — Section 7, not started at all.
- Real Postgres RLS enforcement has never been tested against real
  Postgres in this whole project — every test suite so far runs against
  SQLite, which cannot exercise RLS policies at all (every service's
  README says this explicitly). This is a standing risk, not just a gap.

---

## 4. Build order & current status (THE authoritative table)

| # | Milestone | What | Status | Test count (per that service's own README) |
|---|---|---|---|---|
| 1 | M0 | insynchire-events (+ FIX-M0: 6 agent.* topics, GuardrailEvent) | ✅ Built & verified | 13 |
| 2 | M1 | shared-db + Migration Service (+ FIX-M1: agent/process log tables, `migrate-all-tenants`) | ✅ Built & verified | 5 (shared-db) + 15 (migration_service) |
| 3 | M2 | Auth Service: signup, login, cookies (+ FIX-M2: no direct users_db write, fingerprint genuinely re-validated) | ✅ Built & verified | 28 |
| 4 | M3 | auth-tokens (shared) + Tenant Service (+ FIX-M3: PERMISSION_MATRIX, 410/409/428 status codes) | ✅ Built & verified | 13 (auth-tokens) + 13 (permissions) + 29 (tenant_service) |
| 5 | M4 | User Profile Service: owns users_db, consumes user.registered | ✅ Built & verified | ~15 |
| 6 | M5 | Job Service: posting CRUD, applications, interim public board; + User Profile Service application.submitted consumer | ✅ Built & verified | ~17 (job_service) + 2 (consumer addition) |
| 7 | M6 | Agent Service: all 5 GuardrailService layers + AI Ranking Agent (Graph 2), real interrupt/resume | ✅ Built & verified | 85 |
| 8 | M7 | Notification Service (email) + User Profile Service in-app notification consumer | ✅ Built & verified | 20 (notification_service) + 4 (consumer addition) |
| 9 | M8 | Interview Service: scheduling, join, view (role-scoped visibility) | ✅ Built & verified | 17 (of the combined 32) |
| 10 | M9 | Interview Service: live WebSocket room (chat, code relay + persistence, session state, agent_event plumbing) | ✅ Built & verified | 15 (of the combined 32) |
| 11 | **M10 Slice 1** | Agent Service: Graph 1 (full interview pipeline graph), all nodes, all 3 real interrupts, all named tools (mocked/interim ones flagged) | ⚠️ Built, tested in an **isolated scratch sandbox** — needs re-verification against your real repo (Phase 0) | 37 new (122 total for agent_service) |
| 12 | **M10 Slice 2** | Interview Service: `agent_bridge.py` (in-process Graph 1 driver) + WS gateway wired to `code_update`/new message types (`integrity_event`, `question_request`, `phase_transition_request`, `human_decision`) | ⚠️ Built, tested in an **isolated scratch sandbox** — needs re-verification against your real repo (Phase 0) | 18 new (50 total for interview_service) |
| 13 | **M10 Slice 3** | agent_decision_logs / agent_guardrail_logs real tenant-DB persistence (via TenantResolver, same pattern as every other service) | 🔲 NOT BUILT | — |
| 14 | **FIX-M9** (optional) | `chat_messages` table + `ChatMessageRepository` + real `_handle_chat` persistence, so `fetch_session_transcript_tool` has real data | 🔲 NOT BUILT — needs your explicit go-ahead |  — |
| 15 | **M11** | Real Report Synthesis Agent (replace agent_bridge.py's 3 placeholders with a real LLM provider); wire `end_session`→SESSION_COMPLETED; scorecard approval UX; `scorecard.generated` publish; PDF export | 🔲 NOT BUILT | — |
| 16 | **Stage-3 wiring** | Wire Graph 2's `RankingAgentService` into Job Service (currently built but never called — a standalone gap, not officially numbered in the original plan) | 🔲 NOT BUILT | — |
| 17 | **M12** | Reporting Service (Kafka consumer → reporting_db) + system admin dashboard API | 🔲 NOT BUILT | — |
| 18 | **Task Q** | docker-compose.yml — all services + Redpanda + Redis + PgBouncer + 4 Postgres instances | 🔲 NOT BUILT | — |
| 19 | **M13** | Observability (LangSmith traces, evals), load testing, full security audit (including the first-ever real-Postgres RLS test) | 🔲 NOT BUILT | — |
| 20 | **Frontend (Section 7)** | Angular 18+ app — every feature area | 🔲 NOT BUILT AT ALL | — |

**Total passing tests across the whole backend as of this document:
122 (agent_service) + 50 (interview_service) + 116 (M0–M3 packages) +
~15 (user_profile_service) + ~19 (job_service) + 24 (notification_service
+ its user_profile_service addition) ≈ 346 tests**, of which the 55 in
rows 11–12 need re-verification per Phase 0 below.

---

## 4a. Permission matrix — unchanged from the original plan

See `shared/permissions/permissions/matrix.py` — `PERMISSION_MATRIX`,
covers HTTP routes only. WebSocket message-type authorization for
Interview Service's `/ws/interviews/{session_id}` gateway is enforced
separately, inline in `ws_gateway.py` (`STAFF_ROLES`,
`SESSION_END_ALLOWED_ROLES`, `AGENT_CONTROL_ALLOWED_ROLES`) — this was
true as of M9 and remains true after M10 Slice 2's new message types.

---

## 5. Database schemas — see Section 1's DATABASE MODEL block above for
the current, accurate state of every table that exists. Do not treat
the very first version of this document's schema section as current —
6 tenant-DB migrations have landed since.

---

## 6. Backend service structure — unchanged pattern, one addition

Every service still follows: `route → service → repository → model`.
The one new file class introduced in M10 Slice 2:

```
services/interview_service/interview_service/
  agent_bridge.py   ← THE ONLY file in interview_service that imports
                       agent_service. Owns: CodeUpdateDebouncer,
                       3 placeholder LLM functions (flagged), AgentBridge
                       (wraps InterviewAgentService + GuardrailService).
```

---

## 7. Frontend structure — unchanged from the original plan, NOT STARTED.

---

## 8. Observability & audit logging — mostly unchanged. One correction:
structured JSON logging per service exists informally (each service
uses `logging.basicConfig` + module loggers), but the exact
`{timestamp, level, service, trace_id, tenant_id, session_id, user_id,
event, guardrail_triggered, detail}` shape from the original plan is
NOT uniformly enforced across every log line yet — that's part of
M13's job, not already done.

---

## 9. Interview story — unchanged, still accurate to what's built for
Graph 1/Graph 2 and the 5-layer guardrails. Do not claim the AI Ranking
Agent is "in production use" in an interview — it exists and works but
Job Service never calls it yet (Section 3's gap list).

---

## 10. Security — unchanged from the original plan in full. Every
subsection (10a–10i) still applies to every future module. Re-read it
before building M11, M12, or the frontend.

---

## 11. Guardrails quick-reference — unchanged; `run_guarded_agent_node`
in `agent_service/guardrails/guardrail_service.py` is the concrete,
tested implementation of this section's pseudocode, used by both graphs.

---

## 12. Task prompts

**Moved to `PHASE_PROMPTS.md`.** That file is now the single source of
truth for "what to build next" and "how to verify it" — use it instead
of writing new task prompts from scratch.

---

## 13. Implementation notes, decisions & flagged gaps (M6–M10) — READ BEFORE PHASE 13

This section exists so a fresh agent session (or a fresh human) doesn't
have to re-derive decisions that were already made and tested.

### 13.1 — Why M10 was split into slices, and what "sandbox-verified"
actually means for Slices 1 and 2

M10 Slice 1 (Graph 1) and Slice 2 (WS gateway wiring) were built and
tested in a **separate, isolated scratch environment** that reconstructed
minimal stand-ins for `shared-db`, `auth-tokens`, `permissions`, and
enough of `interview_service`'s own M8/M9 files (models, repositories,
services, config, dependencies, auth_dependency, crypto, ws_tokens,
connection_manager, broadcaster) to genuinely import and exercise the
real `ws_gateway.py` — including 5 real multi-connection WebSocket
tests against a live Uvicorn server. **This is not the same as running
against your actual repository**, which already has the FULL, richer
M8/M9 test suites (`test_join_service.py`, `test_routes_integration.py`,
`test_ws_tokens.py`, `test_ws_gateway_integration.py` — 32 tests total)
that the scratch sandbox did not reconstruct.

**This is exactly why Phase 0 in PHASE_PROMPTS.md exists**: before
building Slice 3, the very first thing to do is drop the Slice 1/2
files (`agent_bridge.py`, the updated `ws_gateway.py`/`dependencies.py`,
and the new test files) into the REAL repository and run BOTH the full
existing M8/M9 suite AND the new Slice 1/2 tests together, to catch any
integration issue the scratch sandbox couldn't see (a stale import, a
signature mismatch, a fixture assumption that doesn't hold against the
real `TenantResolver`/`GlobalUserRepository` implementations).

### 13.2 — AgentBridge: in-process import, not HTTP (Section 2's new row)

Every cross-service interaction built before M10 was either a shared
LIBRARY import or an async KAFKA EVENT — never synchronous
service-to-service HTTP. Agent Service has no HTTP surface. Rather than
silently invent one as a side effect of wiring the WS gateway,
`interview_service/agent_bridge.py` imports the `agent_service` PACKAGE
directly (a normal Python dependency now, in `pyproject.toml`) and
calls `InterviewAgentService` in-process. **If/when Agent Service needs
to scale independently, `agent_bridge.py` is the only file that needs
to change** — swap the in-process call for an HTTP client call; nothing
in `ws_gateway.py` needs to know the difference.

### 13.3 — No real LLM provider anywhere; 3 placeholder functions

`agent_bridge.py` has 3 functions —
`_placeholder_code_analysis_llm_call`, `_placeholder_copilot_llm_call`,
`_placeholder_report_synthesis_llm_call` — each returning a fixed,
clearly-labeled non-answer (e.g., `{"correctness_pct": 50.0}`, chosen
specifically because it never triggers Rule 2.2's sandbox-vs-LLM
contradiction check). **Do not treat any AI-sounding output from this
codebase as real until these are replaced.** This is explicitly M11's
job (Phase 15/16 in PHASE_PROMPTS.md).

### 13.4 — A real bug was found and fixed in Graph 1 (worth knowing the
pattern, in case similar bugs exist elsewhere)

`integrity_node`'s Rule 5.4 escalation flag originally had NO route to
`human_approval_node` in the graph — it set `awaiting_human_approval`
but nothing ever paused there, and nothing ever cleared it either. It
would have stayed `True` forever after the first escalation. Fixed by:
(1) documenting it as an output-signal-only flag (never a graph pause —
the real decision goes through `end_session`, an existing control), and
(2) having `orchestrator_node` clear the flag at the start of every
fresh invocation. **When building Phase 0's re-verification, specifically
re-run `test_integrity_escalation_sets_flag_which_orchestrator_clears_next_time`
and read it carefully** — it's the test that would have caught this bug.

### 13.5 — Known, deliberately-not-yet-fixed gaps (do not silently fix
these as a side effect of some other phase — each needs its own
explicit go-ahead, per this project's own working convention)

- `fetch_session_transcript_tool` always returns `available=False` — no
  `chat_messages` table exists. (FIX-M9, optional, Phase 14.)
- `agent.integrity_flagged`'s Kafka event has no `interviewer_ids` field
  — Notification Service logs a warning and sends nothing. Unchanged
  since M7; still true after M10.
- Job Service never calls `RankingAgentService` — Graph 2 is fully
  built and tested but sits unused. (Phase 16.)
- `run_in_sandbox` never executes code — deliberately mocked per
  Section 10a. Do not wire a real sandbox without a dedicated,
  explicitly-reviewed phase (this is exactly the kind of change Section
  10a asks to be treated with extra care).
- Real Postgres has never run any test in this whole project. RLS
  policies (`_enable_rls()` in every tenant migration) have never
  actually been exercised. This is M13's job, and arguably should not
  wait that long — consider raising this with whoever owns the backlog.
