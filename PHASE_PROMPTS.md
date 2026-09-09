# InSyncHire — PHASE_PROMPTS.md

*Companion to `PROJECT_PLAN.md`. Upload both files into the coding
agent's workspace. Each phase below has a Status, a Build prompt
(paste ONLY that phase's prompt, never more than one phase at a time),
and an exact Verify section. Do not accept "it passed" from the agent
without pasted, real command output.*

**Universal rule for every phase below:** the agent must actually run
the Verify commands itself and paste the real terminal output before
you move on — this document's own instructions to the agent say so,
but you (the human) should also just watch for it.

---

## Phase 0 — Re-verify M10 Slices 1 & 2 against the REAL repository

**Status: 🔲 MUST BE DONE FIRST, before Phase 13.**

### Why this phase exists
M10 Slice 1 (Graph 1) and Slice 2 (WebSocket gateway wiring) were built
and tested in an isolated scratch sandbox that reconstructed minimal
stand-ins for shared packages and interview_service's own M8/M9 files —
NOT your actual repository, which has richer, more complete M8/M9
fixtures and test files. See `PROJECT_PLAN.md` Section 13.1 for the
full explanation. This phase makes sure nothing was missed.

### Build prompt (paste this exactly)

```
Read PROJECT_PLAN.md and this PHASE_PROMPTS.md file in full before
doing anything else. Do not proceed to any other phase.

Phase 0 task: I am about to give you a set of new/changed files for
M10 Slices 1 and 2 (Agent Service's Graph 1, and Interview Service's
agent_bridge.py + updated ws_gateway.py/dependencies.py + two new test
files). These were built and tested in an ISOLATED SCRATCH SANDBOX, not
against this actual repository's full existing test suites.

Your job:
1. Drop the new/changed files into their documented locations (each
   file's first line says exactly where it goes).
2. Update services/agent_service/pyproject.toml and
   services/interview_service/pyproject.toml if needed (Interview
   Service now depends on the agent_service package).
3. Install both packages' dependencies fresh.
4. Run the COMPLETE existing test suite for agent_service (should be
   85 tests from M6, unchanged, PLUS the ~37 new Slice-1 tests = 122
   total) and the COMPLETE existing test suite for interview_service
   (should be the 32 tests from M8/M9, unchanged, PLUS the ~18 new
   Slice-2 tests = 50 total).
5. If ANYTHING fails that did not fail in the scratch sandbox (a stale
   import, a signature mismatch, a fixture assumption that doesn't hold
   against this repo's real TenantResolver/GlobalUserRepository/etc.),
   fix it — do not paper over it, and do not silently change test
   assertions to make them pass. Explain what broke and why.
6. Do NOT touch anything related to Phase 13 (agent_decision_logs
   persistence), Phase 14 (chat_messages), or Phase 15 (real LLM
   provider) in this phase. This phase is verification-only.

Stop after this phase. Give me:
  - The exact pytest commands you ran for BOTH services
  - The exact pasted output (not a summary) showing the real pass
    counts for BOTH services
  - A list of anything you had to fix that the scratch sandbox didn't
    catch, with an explanation of each
Wait for me to confirm before touching Phase 13.
```

### Verify (what you should see pasted back)

```bash
cd services/agent_service
python -m pytest -q
# Expect: 122 passed (85 M6 + 37 M10 Slice 1)

cd ../interview_service
python -m pytest -q
# Expect: 50 passed (32 M8/M9 + 18 M10 Slice 2)
```

If either number differs from what's expected, do not proceed — find
out why first.

---

## Phase 1 — M0: insynchire-events

**Status: ✅ Built & verified.**

### Build prompt
Not needed — already built. If you ever need to rebuild it from
scratch, use this:
```
Using PROJECT_PLAN.md's Context Block, build the insynchire-events
internal Python package exactly as described: Pydantic v2 models for
every Kafka event schema (including all 6 agent.* topics and
GuardrailEvent), publish() with retry + DLQ routing, and subscribe()
consumer setup. No existing schema should ever change without a
schema_version bump.
```

### Verify
```bash
cd shared/insynchire-events
python -m pytest -q
# Expect: 13 passed
```

---

## Phase 2 — M1: shared-db + Migration Service

**Status: ✅ Built & verified.**

### Verify
```bash
cd shared/shared-db && python -m pytest -q       # Expect: 5 passed
cd ../../services/migration_service && python -m pytest -q  # Expect: 15 passed
```

---

## Phase 3 — M2: Auth Service

**Status: ✅ Built & verified.**

### Verify
```bash
cd services/auth_service
python -m pytest -q
# Expect: 28 passed
```

---

## Phase 4 — M3: auth-tokens + Tenant Service + permissions

**Status: ✅ Built & verified.**

### Verify
```bash
cd shared/auth-tokens && python -m pytest -q     # Expect: 13 passed
cd ../permissions && python -m pytest -q          # Expect: 13 passed
cd ../../services/tenant_service && python -m pytest -q  # Expect: 29 passed
```

---

## Phase 5 — M4: User Profile Service

**Status: ✅ Built & verified.**

### Verify
```bash
cd services/user_profile_service
python -m pytest -q
# Expect: all passing (see that service's README for the exact count)
```

---

## Phase 6 — M5: Job Service

**Status: ✅ Built & verified.**

### Verify
```bash
cd services/job_service && python -m pytest -q
cd ../user_profile_service && python -m pytest -q
# Both should be fully green -- M5 added a new consumer to
# user_profile_service (application.submitted -> user_applications_index)
```

---

## Phase 7 — M6: Agent Service (GuardrailService + AI Ranking Agent)

**Status: ✅ Built & verified.**

### Verify
```bash
cd services/agent_service
python -m pytest -q
# Expect: 85 passed (before M10 Slice 1 was added on top)
```

---

## Phase 8 — M7: Notification Service

**Status: ✅ Built & verified.**

### Verify
```bash
cd services/notification_service && python -m pytest -q   # Expect: 20 passed
cd ../user_profile_service && python -m pytest -q          # includes 4 new tests for the in-app notification consumer
```

---

## Phase 9 — M8: Interview Service (scheduling/join)

**Status: ✅ Built & verified.**

### Verify
```bash
cd services/interview_service
python -m pytest -q
# Expect: 32 passed total for M8+M9 combined (17 M8 + 15 M9)
```

---

## Phase 10 — M9: Interview Service (live WebSocket room)

**Status: ✅ Built & verified.**

### Verify
Same command as Phase 9 — M8 and M9 tests live in the same package and
the README documents them together (32 passed total).

---

## Phase 11 — M10 Slice 1: Agent Service Graph 1

**Status: ⚠️ Built in an isolated sandbox — re-verify via Phase 0 above
before trusting this as done.**

### Build prompt
Already delivered. If Phase 0 finds it needs rebuilding, use:
```
Using PROJECT_PLAN.md's AGENTIC AI WORKFLOW section (GRAPH 1) and
Section 13.4 (the integrity_node bug and its fix), build Graph 1 in
services/agent_service/agent_service/graphs/interview_graph.py: the
complete InterviewGraphState TypedDict, every named node
(input_guardrail_node, orchestrator_node, code_analysis_node,
question_strategist_node, integrity_node, copilot_node,
report_synthesis_node, human_approval_node, phase_transition_node,
fallback_node), all 3 real interrupts, and every named tool in
services/agent_service/agent_service/tools/ (sandbox_execution_tool
MOCKED and flagged, complexity_analysis_tool and
difficulty_calibration_tool real/rule-based, rag_question_retrieval_tool
an interim in-memory stand-in, fetch_code_snapshots_tool a thin
formatter, fetch_session_transcript_tool gap-flagged/always
unavailable). Build InterviewAgentService as the entry point. Test
everything for real -- no mocks of the graph itself, genuine
interrupt/resume proven via graph.aget_state(config).next.
```

### Verify
```bash
cd services/agent_service
python -m pytest -q tests/test_interview_tools.py tests/test_interview_graph.py tests/test_interview_agent_service.py
# Expect: 17 + 14 + 6 = 37 passed
python -m pytest -q
# Expect: 122 passed total
```

---

## Phase 12 — M10 Slice 2: Interview Service wired to Graph 1

**Status: ⚠️ Built in an isolated sandbox — re-verify via Phase 0 above
before trusting this as done.**

### Build prompt
Already delivered. If Phase 0 finds it needs rebuilding, use:
```
Using PROJECT_PLAN.md Section 13.2 (the AgentBridge in-process design
decision) and Section 13.3 (the 3 placeholder LLM functions, clearly
labeled, no real provider), build
services/interview_service/interview_service/agent_bridge.py
(CodeUpdateDebouncer + AgentBridge wrapping InterviewAgentService), then
update ws_gateway.py to: debounce code_update into a
maybe_trigger_code_analysis call broadcasting results to
interviewer-role connections only; add integrity_event (any role may
send, result interviewer-only), question_request and
phase_transition_request (staff-only: company_admin/recruiter/
interviewer, NOT observer), and human_decision (staff-only, resumes
whatever interrupt is paused). Do NOT wire end_session to trigger
SESSION_COMPLETED/report_synthesis_node -- that's Phase 15's job.
Update dependencies.py with a process-wide AgentBridge singleton (same
singleton-per-process pattern as _ws_registry/_ws_broadcaster).
Test the new message types with REAL multi-connection WebSocket tests
against a live Uvicorn server (Starlette's TestClient deadlocks on this
gateway's cross-connection broadcast + per-message DB access -- same
reasoning M9's own test file already documented).
```

### Verify
```bash
cd services/interview_service
python -m pytest -q tests/test_agent_bridge.py tests/test_ws_gateway_agent_integration.py
# Expect: 13 + 5 = 18 passed
python -m pytest -q
# Expect: 50 passed total
```

---

## Phase 13 — M10 Slice 3: agent_decision_logs / agent_guardrail_logs persistence

**Status: 🔲 NOT BUILT. Do this only after Phase 0 confirms Slices 1/2
are genuinely green in the real repo.**

### Build prompt
```
Read PROJECT_PLAN.md in full, especially Section 1's tenant DB table
list (agent_decision_logs and agent_guardrail_logs already exist,
migration 0003_agent_and_process_logs) and Section 11 (guardrails
quick-reference).

Build ONLY Phase 13 from PHASE_PROMPTS.md -- nothing from Phase 14
onward.

Task: wire GuardrailService's in-process logged_events to REAL tenant
DB writes, using the exact same TenantResolver pattern
interview_service/job_service/tenant_service already use (repository
pattern: a new AgentDecisionLogRepository and
AgentGuardrailLogRepository in agent_service, or -- since agent_service
has no TenantResolver of its own today -- decide explicitly whether
this write belongs in agent_service (would need its own TenantResolver,
duplicating that wiring) or in interview_service (which already has
one, via agent_bridge.py calling back into it after each graph
invocation). Follow this project's own established precedent for
exactly this kind of question: FIX-M2 (never let a service write a
table it doesn't have a clean read path to) and M5's
ApplicationSubmittedConsumerService (the service that owns the DATABASE
does the write, triggered by the caller). State which option you're
choosing and why before writing code.

Also wire AgentBridge to pass a real `publish` callable into
GuardrailService (currently it does not), so agent.guardrail_triggered
actually reaches Kafka in a live interview, not just in tests.

Also decide and implement: does every guardrail check get persisted
(the plan says "even PASSED events are sampled and logged" -- decide
what "sampled" means concretely, e.g. always log BLOCKED/SANITIZED/
FLAGGED, sample 1-in-N for PASSED) or every single one? State your
choice and reasoning.

Test everything for real against a real (or realistic SQLite stand-in,
following this codebase's own established testing conventions) tenant
DB -- prove rows actually land in agent_decision_logs/
agent_guardrail_logs after a real graph invocation.

After this phase is built, stop. Give me the exact verification
commands and wait for me to confirm they pass before touching Phase 14.
```

### Verify (fill in exact commands once the agent tells you which
package(s) it touched)
```bash
cd services/agent_service        # or interview_service, depending on the decision above
python -m pytest -q
# Expect: all previously-passing tests still pass, PLUS new tests
# proving real DB rows are created
```

---

## Phase 14 — FIX-M9: chat_messages table (OPTIONAL)

**Status: 🔲 NOT BUILT. Needs your explicit go-ahead — do not let the
agent build this as a side effect of any other phase.**

### Build prompt (only paste this if you've decided you want it)
```
Build ONLY Phase 14 from PHASE_PROMPTS.md -- nothing from Phase 15
onward.

Task: add a chat_messages table to the tenant Alembic chain (new
revision, e.g. 0007_chat_messages, extending the SAME chain -- never a
second chain, per every prior migration's own docstring). Columns:
message_id, tenant_id, session_id, from_user_id, from_role, body,
sent_at. RLS + tenant_id column, same pattern as every other tenant
table since 0004. Add a ChatMessageRepository in interview_service.
Update ws_gateway.py's _handle_chat to persist every message (it
currently only relays). Update agent_service's
fetch_session_transcript_tool to accept real fetched messages (same
"thin formatter, real fetch stays in the owning service" pattern
fetch_code_snapshots_tool already established) and update
TranscriptFetchResult.available to reflect real data when messages
exist.

Test for real: persisted messages survive a reconnect, are ordered
correctly, and fetch_session_transcript_tool's formatter produces
correct output from real fetched rows.

After this phase is built, stop. Give me the exact verification
commands and wait for me to confirm they pass before touching Phase 15.
```

### Verify
```bash
cd services/interview_service
python -m pytest -q
# Expect: all previous tests + new chat persistence tests, all passing
```

---

## Phase 15 — M11 Part 1: Wire a real LLM provider

**Status: 🔲 NOT BUILT.**

### Build prompt
```
Read PROJECT_PLAN.md Section 13.3 in full before starting.

Build ONLY Phase 15 from PHASE_PROMPTS.md -- nothing from Phase 16
onward.

Task: replace agent_bridge.py's 3 placeholder LLM functions
(_placeholder_code_analysis_llm_call, _placeholder_copilot_llm_call,
_placeholder_report_synthesis_llm_call) with real calls to [DECIDE:
Anthropic API / OpenAI API / other -- ask me which if it's not already
obvious from other parts of this codebase]. Keep the exact same
function signatures (wrapped <candidate_data> prompt in, matching
return shape out) so nothing else in agent_bridge.py or
interview_graph.py needs to change. Handle real API failures (timeout,
rate limit, malformed response) by routing to Graph 1's existing
fallback_node mechanism -- do NOT let a real API failure crash a live
interview session (Rule 5.1 already requires this; make sure it
actually holds for real API errors, not just guardrail-triggered ones).

Never hardcode an API key -- env var / secrets manager only (Section
10i, unchanged).

Test with a real (or realistically mocked, if you don't want to spend
real API credits in CI) LLM call, and prove the guardrail layers still
correctly validate real (not placeholder) LLM output.

After this phase is built, stop. Give me the exact verification
commands and wait for me to confirm before touching Phase 16.
```

### Verify
```bash
cd services/agent_service && python -m pytest -q
cd ../interview_service && python -m pytest -q
# Both fully green; agent_bridge.py's placeholder functions should be gone
```

---

## Phase 16 — M11 Part 2: Scorecard approval workflow + PDF export

**Status: 🔲 NOT BUILT.**

### Build prompt
```
Read PROJECT_PLAN.md Section 1's STAGE 7 status and Section 2's
"report_synthesis_node / scorecard workflow" decision row before
starting.

Build ONLY Phase 16 from PHASE_PROMPTS.md -- nothing from Phase 17
onward.

Task: wire ws_gateway.py's end_session to ALSO trigger Graph 1's
SESSION_COMPLETED (report_synthesis_node) after marking the interview
COMPLETED (order matters -- the session should already be marked
complete before scorecard generation starts, so a slow scorecard
generation never blocks the interviewer from leaving the room). Add a
new tenant DB table for scorecards (scorecards, scorecard_approvals --
Section 1's original schema listing has the columns) via a new Alembic
revision extending the SAME tenant chain. On scorecard APPROVAL
(human_decision with approval_type=SCORECARD), persist the final
scorecard and publish scorecard.generated (already-registered event
schema, already consumed by Notification Service and User Profile
Service since M7 -- should "just work" the same way interview.scheduled
did in M8). Add a PDF export endpoint (Section 4a mentions
GET /scorecards/{id}/pdf, already in PERMISSION_MATRIX).

Test everything for real: a full session -> end -> report_synthesis ->
human approval -> scorecard.generated published -> PDF export flow, end
to end.

After this phase is built, stop. Give me the exact verification
commands and wait for me to confirm before touching Phase 17.
```

### Verify
```bash
cd services/interview_service && python -m pytest -q
# Full end-to-end scorecard flow test should be present and passing
```

---

## Phase 17 — Stage 3 wiring: connect Graph 2 (AI Ranking Agent) to Job Service

**Status: 🔲 NOT BUILT (standalone gap, not in the original milestone
numbering, but real).**

### Build prompt
```
Read PROJECT_PLAN.md Section 3's "AI Ranking Agent (Graph 2) is built
but never called from Job Service" gap before starting.

Build ONLY Phase 17 from PHASE_PROMPTS.md -- nothing from Phase 18
onward.

Task: decide and document the SAME in-process-vs-HTTP question
Section 13.2 already resolved for Interview Service/Agent Service --
apply the SAME answer (in-process import) for consistency unless you
have a specific reason not to. Wire Job Service's applicant-list
endpoint (GET /jobs/{id}/applicants, Section: "Triggers AI Ranking
Agent when recruiter opens applicant list") to call
RankingAgentService.start_ranking() the first time it's opened for a
job, persist ai_rank/ai_rank_evidence onto job_applications (Job
Service already owns this table), and expose the recruiter's
approve/reject decision as a call to resume_after_human_decision().

Test end-to-end: post a job, apply as 2+ candidates, open the applicant
list, prove ranking runs and ai_rank/ai_rank_evidence get persisted,
prove recruiter approval publishes agent.ranking_completed.

After this phase is built, stop. Give me the exact verification
commands and wait for me to confirm before touching Phase 18.
```

### Verify
```bash
cd services/job_service && python -m pytest -q
```

---

## Phase 18 — M12: Reporting Service + system admin dashboard

**Status: 🔲 NOT BUILT.**

### Build prompt
```
Read PROJECT_PLAN.md's full original Reporting Service description
(Section 1's SERVICES list, item 9) before starting.

Build ONLY Phase 18 from PHASE_PROMPTS.md -- nothing from Phase 19
onward.

Task: build reporting_db's schema (tenant_stats, user_stats, job_stats,
interview_stats, agent_stats, error_logs, guardrail_logs, audit_trail,
kafka_consumer_lag), the Reporting Service as a headless Kafka consumer
of EVERY topic in insynchire_events.Topics, and a system-admin-only API
surface (tenant list/stats, error logs, guardrail trigger frequency,
audit trail) -- system_admin role only, per PERMISSION_MATRIX's
existing /admin/* entries. Once this exists, replace Job Service's
interim /public/jobs board (documented stopgap since M5) with a real
reporting_db aggregate read, and remove the interim
"scan every tenant DB directly" implementation.

Test everything for real.

After this phase is built, stop. Give me the exact verification
commands and wait for me to confirm before touching Phase 19.
```

### Verify
```bash
cd services/reporting_service && python -m pytest -q
cd ../job_service && python -m pytest -q   # public board should still pass, now via the real aggregate
```

---

## Phase 19 — Task Q: docker-compose.yml

**Status: 🔲 NOT BUILT.**

### Build prompt
```
Build ONLY Phase 19 from PHASE_PROMPTS.md -- nothing from Phase 20
onward.

Task: write docker-compose.yml for local dev: all services built so
far (auth, tenant, user_profile, job, agent [no HTTP server -- confirm
whether it needs a container at all if it's only ever called
in-process by interview_service, per Section 13.2's decision --
otherwise this phase itself may be what finally forces an HTTP surface
for Agent Service; make that decision explicitly and document it the
same way Section 13.2 documented the in-process decision], interview,
notification, migration, reporting), Redpanda (Kafka), Redis, PgBouncer,
4 PostgreSQL instances, insynchire-events package as a shared mounted
volume or installed wheel, LangSmith env config placeholder.

Test: `docker compose up` brings up a working local environment; run
LOCAL_APP_SETUP.md's manual curl walkthrough against it and confirm it
still works end to end.

After this phase is built, stop and confirm the full docker compose
walkthrough with me before touching Phase 20.
```

### Verify
Manual: `docker compose up`, then run through `LOCAL_APP_SETUP.md`'s
existing curl walkthrough end to end against the composed environment.

---

## Phase 20 — M13: Observability, load testing, and the FIRST real
Postgres RLS test

**Status: 🔲 NOT BUILT. Flagged in PROJECT_PLAN.md Section 13.5 as
possibly worth doing earlier than "last" — use your judgment.**

### Build prompt
```
Read PROJECT_PLAN.md Section 3's closing paragraph (about RLS never
having been tested against real Postgres) before starting.

Build ONLY Phase 20 from PHASE_PROMPTS.md.

Task, in this order:
1. Stand up a REAL Postgres instance (via the now-existing
   docker-compose.yml from Phase 19) and write the FIRST real
   integration test in this entire project that provisions a real
   tenant DB, confirms RLS policies actually block cross-tenant reads
   at the database engine level (not just the repository-level
   tenant_id filter every test so far has exercised against SQLite,
   which cannot enforce RLS at all). This is the single most important
   test in this phase -- do not skip it or treat it as optional.
2. Wire LangSmith tracing into both LangGraph graphs (Graph 1 and
   Graph 2).
3. Write evals for guardrail correctness and agent output quality.
4. Run a basic load test against the WebSocket gateway (multiple
   simultaneous interview rooms).
5. Do a full pass over Section 10's security posture against the
   ACTUAL deployed code (not just what the code comments claim) --
   produce a written audit noting any gap between claimed and actual
   behavior.

After this phase, stop and walk me through the RLS test results and
the security audit findings before considering this project
"production-ready."
```

### Verify
Manual review of the RLS test output + the written security audit --
there is no single pytest command that verifies this phase.

---

## Phase 21+ — Frontend (Angular, Section 7)

**Status: 🔲 NOT BUILT AT ALL.**

This is a large enough body of work that it deserves its own
phase-by-phase breakdown once you get here — do not ask an agent to
"build the frontend" in one shot. When you're ready, come back and
we'll write a proper Phase 21a/21b/21c... breakdown mirroring
Section 7's feature areas (auth, dashboard, jobs, interviews/live-room,
scorecards, admin, tenant-settings), the same way M10 was split into
slices.
