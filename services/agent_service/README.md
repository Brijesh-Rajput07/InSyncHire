# LOCATION: services/agent_service/README.md

# Agent Service (M6 — GuardrailService + AI Ranking Agent, Tasks I & J)

Owns the LangGraph agent nodes and the **GuardrailService**: the
5-layer defense-in-depth wrapper every agent call in the system goes
through (Section: GUARDRAILS ARCHITECTURE). M6 is now complete: the
GuardrailService (Task I) plus a real, working LangGraph implementation
of **GRAPH 2 — the AI Ranking Agent** (Task J), including a genuine
human-in-the-loop interrupt (not simulated).

## What this milestone delivers

- **Layer 1 — Input Guardrails** (`guardrails/input_guardrails.py`):
  prompt-injection stripping (Rule 1.1), per-agent input length limits
  (Rule 1.2), input schema validation (Rule 1.3), and the mandatory
  `<candidate_data>` XML delimiter wrap (Rule 1.4).
- **Layer 2 — Output Guardrails** (`guardrails/output_guardrails.py`):
  Pydantic schema enforcement with unknown-field dropping (Rule 2.1),
  agent-specific semantic consistency checks — code analysis vs sandbox,
  ranking evidence vs job requirements, report synthesis recommendation
  vs dimension scores (Rule 2.2) — hallucination detection against known
  evidence IDs (Rule 2.3), and the forbidden-field check that blocks
  entirely on any auto-decision field like `verdict`/`hire_recommendation`
  (Rule 2.4).
- **Layer 3 — Bias & Fairness Guardrails** (`guardrails/bias_guardrails.py`):
  demographic language detection (Rule 3.1), comparative/proxy-bias
  detection across ranked candidates (Rule 3.2), and scoring-consistency
  checks across near-identical submissions (Rule 3.3).
- **Layer 4 — PII Guardrails** (`guardrails/pii_guardrails.py`):
  name/email/phone/university redaction on scorecards (Rule 4.1) and
  cross-candidate evidence-leakage detection (Rule 4.2).
- **Layer 5 — Behavioral / Fallback Guardrails** (`guardrails/behavioral_guardrails.py`):
  a sliding-window circuit breaker (Rule 5.2), an integrity-signal
  escalation tracker (Rule 5.4), pure decision logic for the three named
  human-in-the-loop timeout behaviors (Rule 5.3), and the fallback
  decision builder that never surfaces errors to the candidate (Rule 5.1).
- **`GuardrailService`** (`guardrails/guardrail_service.py`): the single
  class that wires all 5 layers together, logs *every* check (including
  PASSED ones, per the plan's "no exceptions" rule) and — only when a
  `publish` callable is supplied — turns each check into the SHARED
  `insynchire_events.schemas.GuardrailEvent`/`AgentGuardrailTriggeredEvent`
  and publishes it to `agent.guardrail_triggered`. No new event schema was
  defined; this milestone reuses FIX-M0's existing `GuardrailEvent` exactly
  as instructed.
- **`run_guarded_agent_node`**: the concrete implementation of Section
  11's "every agent node follows this structure" wrapper pseudocode —
  input guardrails → circuit breaker check → LLM call (always on
  `<candidate_data>`-wrapped text) → output guardrails with bounded
  retry → bias scan (if the caller supplies a text-field extractor) →
  fallback on any failure.
- **NeMo Guardrails Colang skeleton** (`colang/config.yml`,
  `colang/guardrails.co`): the three flows named verbatim in Rule 5.5,
  plus the candidate-data-isolation flow from Rule 1.4. This is a
  **config skeleton only** — `nemoguardrails` is not a runtime
  dependency of this service yet; every rule above is implemented
  natively in Python so the service is fully unit-testable without it.
  Wire NeMo Guardrails in for real once a live LLM call exists (M10).

## What this milestone deliberately does NOT include

Per the M6 task brief: no persistence to `agent_decision_logs` /
`agent_guardrail_logs` / `job_applications.ai_rank` in a real tenant DB,
and no LangGraph interview pipeline (Graph 1 — that's M10). `GuardrailService.logged_events`
is an in-process list for testability/inspection only — it is not a
substitute for the real audit trail. When persistence is wired up
(M10), follow the exact `TenantResolver` pattern already established in
`tenant_service` / `job_service`: open a session scoped to the session's
`tenant_id`, write through a repository, never inline SQL in the
guardrail layer itself. Writing the ranking result into
`job_applications.ai_rank`/`ai_rank_evidence` is Job Service's job (it
owns that table) — a future Job Service Kafka consumer for
`agent.ranking_completed`, following the exact same
no-cross-service-DB-writes precedent FIX-M2 established and M5's
`user_applications_index` consumer already follows.

## Task J — the AI Ranking Agent (GRAPH 2)

A real, compiled `langgraph.graph.StateGraph` implementing Section:
GRAPH 2 exactly:[input_guardrail_node] -> [ranking_agent_node] -> [output_guardrail_node]
-> [bias_scan_node] -> [human_approval_node (interrupt)] -> [END]

- **`RankingGraphState`** (`graphs/ranking_graph.py`): the TypedDict
  state threaded through the graph — job opening, candidate profiles,
  historical jobs, sanitized bios, the raw/validated ranking output,
  the human-approval flag, and blocked/block_reason.
- **`profile_scorer_tool`** (`tools/profile_scorer_tool.py`): the
  **rule-based, non-LLM** numeric scorer named in Section 2's
  architecture-decision table ("Reduces bias amplification vs
  LLM-scored ranking"). It only ever reads `skills`/`experience_years`
  — never `bio`, `resume_text`, or `university` — so there is nothing
  in scoring an LLM prompt-injection attempt could influence.
- **`rag_job_similarity_tool`** (`tools/rag_job_similarity_tool.py`):
  **interim implementation** (same documented pattern as
  `job_service/services/public_board_service.py`) — a Jaccard
  skill-overlap similarity stand-in for the real pgvector search
  against `question_bank`/`successful_hire_profiles`, which doesn't
  exist until later milestones. Advisory context only; it never
  affects the rule-based score. Swap the function body for a real
  `SELECT ... ORDER BY embedding <-> :query_vec` once pgvector-backed
  tenant tables exist — the signature is designed not to need to change.
- **LLM usage is scoped to exactly one thing**: synthesizing each
  candidate's `evidence_narrative`, per Section: "LLM used only for
  synthesizing the evidence narrative per candidate, NOT for the
  numeric ranking." The numeric `match_score`/`matched_skills`/`gaps`
  never touch the LLM.
- **Guardrails wired in exactly where the plan puts them**: Layer 1 on
  each candidate's bio before it enters the narrative-synthesis prompt;
  Layer 2 (schema + Rule 2.2's ranking-specific consistency check —
  "evidence_narrative doesn't reference any skill from the job
  requirements" — + Rule 2.3 hallucination check) on the assembled
  `RankingResult`; Layer 3 (demographic-language + comparative-bias
  detection) on every narrative. A **BLOCKED** verdict at any of these
  three nodes routes the graph straight to `END` via a conditional
  edge — it never reaches (or pauses at) `human_approval_node`. A
  **FLAGGED** verdict (e.g. Rule 2.2's missing-skill-reference case)
  does *not* halt the graph — the result still reaches human review,
  matching Section: "recruiter sees ranking WITH evidence. Makes final
  call. AI output is advisory."
- **The human-approval interrupt is real**, not simulated: the graph is
  compiled with `interrupt_before=["human_approval_node"]` and a
  `MemorySaver` checkpointer — `start_ranking()` genuinely pauses
  execution there (`graph.aget_state(config).next == ("human_approval_node",)`),
  and `resume_after_human_decision()` resumes it from that exact
  checkpoint via `graph.aupdate_state()` + `graph.ainvoke(None, config)`.
  See `test_graph_genuinely_pauses_before_human_approval` for the proof.
- **`RankingAgentService`** (`services/ranking_agent_service.py`): the
  actual entry point — compiles the graph once, exposes `start_ranking()`
  and `resume_after_human_decision()`, and publishes the SHARED
  `insynchire_events.schemas.AgentRankingCompletedEvent` to
  `agent.ranking_completed` **only** on an approved, unblocked run
  (never on rejection, never on a blocked run) — reusing FIX-M0's
  existing schema exactly, per the same "don't redefine it" instruction
  Task I followed for `GuardrailEvent`.

## Install

```bash
cd insynchire
pip install -e shared/insynchire-events   # only needed if you pass `publish=` to GuardrailService/RankingAgentService
pip install -e "services/agent_service[dev]"
```

## Run the tests (no Postgres/Redis/Kafka required)

```bash
cd services/agent_service
python -m pytest -q
```

Expected: `85 passed`.

Every rule named in the project plan's GUARDRAILS ARCHITECTURE section
has at least one dedicated test; `test_guardrail_service.py` additionally
proves the layers compose correctly end-to-end through
`run_guarded_agent_node`. `test_ranking_tools.py` covers the rule-based
scorer and the RAG similarity stand-in in isolation; `test_ranking_graph.py`
drives the REAL compiled LangGraph graph (not a mock of it) through
every path: clean success + genuine interrupt/resume, a FLAGGED
(non-halting) Rule 2.2 case, a BLOCKED (halting) Rule 3.1 case, and
`RankingAgentService`'s approve/reject/unknown-thread behavior.

## Usage

```python
from agent_service.guardrails import GuardrailService, run_guarded_agent_node
from agent_service.schemas import CodeAnalysisResult

guardrail_service = GuardrailService(publish=event_producer.publish)  # publish is optional

async def call_llm(prompt: str) -> dict:
    response = await llm.ainvoke(prompt)
    return response.parsed_json  # raw, not-yet-validated dict

result = await run_guarded_agent_node(
    guardrail_service=guardrail_service,
    agent_name="code_analysis",
    node_name="code_analysis_node",
    candidate_text=current_code,
    schema_model=CodeAnalysisResult,
    llm_call=call_llm,
    sandbox_passed_tests=sandbox_result.passed_tests,
    tenant_id=state.tenant_id,
    session_id=state.session_id,
    trace_id=trace_id,
)

from agent_service.schemas import FallbackDecision
if isinstance(result, FallbackDecision):
    # route to fallback_node -- interviewer sees result.interviewer_message,
    # candidate sees nothing (result.surface_to_candidate is always False)
    ...
else:
    # result is a validated CodeAnalysisResult -- update state, continue graph
    ...
```

### AI Ranking Agent (Task J)

```python
from agent_service.services import RankingAgentService
from agent_service.schemas import JobOpeningInput, CandidateProfileInput

ranking_service = RankingAgentService(
    guardrail_service=guardrail_service,
    narrative_llm_call=call_llm_for_narrative,   # async (prompt: str) -> str
    publish=event_producer.publish,               # optional
)

# STAGE 3, step 1: kick off ranking, pauses before human approval
start_result = await ranking_service.start_ranking(
    job_opening=JobOpeningInput(job_id=job.job_id, title=job.title, description=job.description, skills_tags=job.skills_tags),
    candidate_profiles=[
        CandidateProfileInput(user_id=c.user_id, skills=c.skills, experience_years=c.experience_years, bio=c.bio)
        for c in applicants
    ],
    historical_jobs=past_jobs,   # optional, [] for a brand-new tenant
    tenant_id=tenant_id,
    trace_id=trace_id,
)
if start_result.blocked:
    # a guardrail blocked the run before it ever reached human review
    ...
else:
    # recruiter reviews start_result.ranking_result (evidence per candidate)
    ...

# STAGE 3, step 2: recruiter approves (or rejects) -- resumes the SAME
# paused graph run from its checkpoint
final_result = await ranking_service.resume_after_human_decision(
    thread_id=start_result.thread_id, approved=True, trace_id=trace_id,
)
# final_result.published is True only on an approved, unblocked run --
# that's when agent.ranking_completed was actually published
```

## Folder contents
```text
services/agent_service/
├── pyproject.toml
├── .env.example
├── README.md
├── agent_service/
│ ├── init.py
│ ├── config.py
│ ├── schemas/
│ │ ├── init.py
│ │ ├── guardrail_schemas.py ← GuardrailCheckResult + per-layer result dataclasses
│ │ ├── agent_io_schemas.py ← CodeAnalysisResult, SuggestedQuestion, IntegritySignal,
│ │ │ CoPilotSuggestion, RankingResult, Scorecard
│ │ └── ranking_schemas.py ← JobOpeningInput, CandidateProfileInput (Task J inputs)
│ ├── guardrails/
│ │ ├── init.py
│ │ ├── patterns.py ← shared regex/term libraries (Layers 1, 3, 4)
│ │ ├── input_guardrails.py ← Layer 1
│ │ ├── output_guardrails.py ← Layer 2
│ │ ├── bias_guardrails.py ← Layer 3
│ │ ├── pii_guardrails.py ← Layer 4
│ │ ├── behavioral_guardrails.py ← Layer 5
│ │ └── guardrail_service.py ← orchestrator + run_guarded_agent_node
│ ├── tools/ ← Task J's two named LangGraph tools
│ │ ├── init.py
│ │ ├── profile_scorer_tool.py ← rule-based (NOT LLM) numeric scorer
│ │ └── rag_job_similarity_tool.py ← interim Jaccard stand-in for pgvector search
│ ├── graphs/ ← Task J's compiled LangGraph graph
│ │ ├── init.py
│ │ └── ranking_graph.py ← RankingGraphState + GRAPH 2, real interrupt_before
│ ├── services/ ← Task J's orchestration entry point
│ │ ├── init.py
│ │ └── ranking_agent_service.py ← RankingAgentService (start/resume/publish)
│ └── colang/
│ ├── config.yml
│ └── guardrails.co
└── tests/
├── conftest.py
├── test_input_guardrails.py
├── test_output_guardrails.py
├── test_bias_guardrails.py
├── test_pii_guardrails.py
├── test_behavioral_guardrails.py
├── test_guardrail_service.py
├── test_ranking_tools.py ← profile_scorer_tool + rag_job_similarity_tool
└── test_ranking_graph.py ← real compiled graph, genuine interrupt/resume
```
## Config knobs (see `.env.example`)

All 5 layers' tunable numbers are environment-configurable via
`AgentServiceConfig` (`config.py`) rather than hardcoded — input length
limits per agent, circuit breaker window/max-triggers/cooldown,
integrity escalation threshold/window, and the output-schema retry
count. `GUARDRAIL_DEBUG_LOG_ENABLED` is the same dev-only console-log
stopgap pattern as `OTP_DEBUG_LOG_ENABLED` / `INVITE_DEBUG_LOG_ENABLED`
in earlier services — never enable it in a real deployment (the real
audit trail is `agent_guardrail_logs` + `reporting_db`, not stdout).

## Architectural note: why forbidden-field checking happens on the raw dict, not the validated model

`agent_io_schemas.py`'s `IntegritySignal` and `CodeAnalysisResult` use
`ConfigDict(extra="forbid")`. Rule 2.1 says unknown fields should be
*dropped*, which would normally argue for `extra="ignore"` — but Rule
2.4's forbidden-field check needs to see whether the raw LLM output
*attempted* to include a field like `verdict` before that attempt is
silently discarded, because the attempt itself is the signal worth
blocking on (an agent trying to sneak in an auto-decision field is more
concerning than an agent inventing an irrelevant field). So
`output_guardrails.py` checks the raw dict for forbidden keys FIRST
(Rule 2.4), and only afterward filters the dict down to known field
names before Pydantic validation (Rule 2.1) — `extra="forbid"` on the
models then acts as a second independent backstop against ever
constructing one of these objects with a forbidden field, the same
"two independent layers" discipline used everywhere else in this
codebase (RLS + repository-level tenant scoping, etc.).