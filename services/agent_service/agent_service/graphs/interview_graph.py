# LOCATION: services/agent_service/agent_service/graphs/interview_graph.py

"""
GRAPH 1 -- INTERVIEW PIPELINE GRAPH (Section: AGENTIC AI WORKFLOW).

Owned by Agent Service (Section 3: "Agent Service ... Owns the
LangGraph graph definition and all agent nodes"), built on the exact
same primitives M6's `ranking_graph.py` (GRAPH 2) already proved out in
this codebase: a real `langgraph.graph.StateGraph`, a `MemorySaver`
checkpointer keyed by `thread_id` (here: the interview `session_id`),
and genuine `interrupt_before` pauses -- not simulated flags.

*** ARCHITECTURAL DECISION: one `.ainvoke()` per incoming event, not
one long-running call ***
The plan describes `orchestrator_node` routing on a `trigger` and, for
some triggers, routing "back to orchestrator_node" (e.g. `integrity_node`)
or looping (`question_strategist_node` on a REJECTED suggestion). A
live interview session is fundamentally event-driven -- a WebSocket
`code_update`, a client-reported integrity signal, an interviewer's
approve/reject click -- each arriving at a different, unpredictable
time, sometimes minutes apart. Modeling that as one single
`.ainvoke()` call that blocks in a loop for the session's whole
duration would be both impractical (holding an open coroutine for a
45-minute interview) and wrong for LangGraph's own checkpoint/resume
model, which is built around exactly this "one invocation per event,
state persisted between them via `thread_id`" shape (the same shape
`ranking_graph.py` already uses across its `start_ranking` +
`resume_after_human_decision` calls).

So: **this graph is invoked once per incoming trigger event.** Each
node that the plan describes as "routes back to orchestrator_node" is
instead the terminal node for THAT invocation -- the next real-world
event (the next WebSocket message, the next interviewer decision)
triggers the next `.ainvoke()`, which reads the exact state the
previous invocation left behind. `orchestrator_node` is the graph's
entry point for every invocation, exactly as specified; it just isn't
a node the graph loops back into WITHIN one invocation.

Slice 2 (not built in this response -- see the continuation prompt's
own staging) wires `interview_service`'s WebSocket gateway
(`ws_gateway.py`) to actually call `InterviewAgentService.handle_trigger()`
below on `code_update`/integrity-event messages, and to route the
interviewer's approve/edit/reject/confirm messages to
`resume_after_human_decision()`. Until that lands, this graph is
complete, real, and independently tested, but nothing in
`interview_service` calls it yet -- the exact same "structurally
complete, not yet wired to a live trigger" state M6's Graph 2 was in
before Job Service existed to call `RankingAgentService`.

HUMAN-IN-THE-LOOP INTERRUPTS (3, per the plan):
  1. Question approval -- `human_approval_node` (approval_type=QUESTION)
  2. Scorecard approval -- `human_approval_node` (approval_type=SCORECARD)
  3. Phase transition confirmation -- `phase_transition_node` (itself
     the interrupt point, per the plan's own listing of it as a
     separate "HUMAN-IN-THE-LOOP INTERRUPT #3" node, distinct from
     `human_approval_node`)

`human_approval_node` is REUSED for interrupts #1 and #2 (matching the
plan's `human_approval_type: str | None  # "QUESTION" | "SCORECARD" |
"PHASE_END"` field design -- one node, branching on that field) rather
than two separate LangGraph nodes, since the plan explicitly describes
it as one node serving multiple approval types.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from ..guardrails import GuardrailService, run_guarded_agent_node
from ..schemas.agent_io_schemas import CodeAnalysisResult, CoPilotSuggestion, IntegritySignal, Scorecard, SuggestedQuestion
from ..schemas.guardrail_schemas import FallbackDecision
from ..tools import (
    CandidateQuestion,
    analyze_complexity,
    calibrate_difficulty,
    retrieve_candidate_questions,
    run_in_sandbox,
)
from ..tools.fetch_session_transcript_tool import fetch_session_transcript

_INTERVIEW_TRIGGER_TO_NODE = {
    "CODE_DIFF_MEANINGFUL": "code_analysis_node",
    "QUESTION_REQUEST": "question_strategist_node",
    "INTEGRITY_EVENT": "integrity_node",
    "PHASE_TRANSITION": "phase_transition_node",
    "SESSION_COMPLETED": "report_synthesis_node",
}

AGENT_CODE_ANALYSIS = "code_analysis"
AGENT_QUESTION_STRATEGIST = "question_strategist"
AGENT_INTEGRITY = "integrity"
AGENT_COPILOT = "copilot"
AGENT_REPORT_SYNTHESIS = "report_synthesis"

Trigger = Literal[
    "CODE_DIFF_MEANINGFUL", "QUESTION_REQUEST", "INTEGRITY_EVENT", "PHASE_TRANSITION", "SESSION_COMPLETED",
]
Phase = Literal["WAITING", "IN_PROGRESS", "CODING_ROUND", "SYSTEM_DESIGN_ROUND", "WRAP_UP", "COMPLETED"]

CodeAnalysisLLMCallFn = Callable[[str], Awaitable[dict[str, Any]]]
"""Wrapped <candidate_data> prompt in, raw dict out -- same contract as
M6's `run_guarded_agent_node`'s `llm_call`. Expected to return a dict
matching `CodeAnalysisResult`'s fields except `correctness_pct`/
`passed_tests`/`failed_tests`, which the sandbox tool result
overrides/validates against (Rule 2.2)."""

NarrativeLLMCallFn = Callable[[str], Awaitable[str]]
"""Wrapped prompt in, plain narrative text out -- same shape as M6's
`NarrativeLLMCallFn` for the ranking graph's evidence narrative."""


class InterviewGraphState(TypedDict):
    # Session identity
    session_id: str
    tenant_id: str | None
    candidate_user_id: str | None
    interviewer_ids: list[str]

    # Session phase state machine
    phase: Phase
    phase_history: list[dict]
    pending_phase: Phase | None
    """Set by orchestrator_node on a PHASE_TRANSITION trigger, read by
    phase_transition_node on resume -- not itself in the plan's schema
    listing but needed to carry "what phase are we transitioning TO"
    across the interrupt pause."""

    # Trigger for THIS invocation (Section: orchestrator_node's own
    # routing input) -- not persisted meaningfully across invocations,
    # just how the caller tells this invocation what happened.
    trigger: Trigger | None
    trigger_payload: dict
    """Raw event-specific data for this invocation: the code diff text
    for CODE_DIFF_MEANINGFUL, the raw integrity event for
    INTEGRITY_EVENT, {} otherwise."""

    # Code editor state
    current_code: str
    current_language: str
    code_snapshot_ids: list[str]
    last_meaningful_diff: str

    # Question state
    current_question: dict | None
    question_history: list[dict]
    suggested_question: dict | None
    human_approved_question: bool

    # Agent outputs (accumulated across session)
    code_analysis_results: list[dict]
    integrity_signals: list[dict]
    copilot_suggestions: list[dict]

    # Guardrail state
    guardrail_log: list[dict]
    last_guardrail_action: str | None

    # Human-in-the-loop flags
    awaiting_human_approval: bool
    human_approval_type: str | None  # "QUESTION" | "SCORECARD" | "PHASE_END"
    human_decision: str | None  # "APPROVED" | "EDITED" | "REJECTED" | "CONFIRMED" | None

    # Final output
    scorecard: dict | None
    scorecard_approved: bool

    # Fallback signaling for this invocation (not in the plan's schema
    # verbatim, but needed so the caller can tell a FallbackDecision
    # happened without re-deriving it from last_guardrail_action alone)
    fallback_reason: str | None


def initial_interview_state(
    *, session_id: uuid.UUID, tenant_id: uuid.UUID | None, candidate_user_id: uuid.UUID | None,
    interviewer_ids: list[uuid.UUID],
) -> InterviewGraphState:
    """Builds a fresh state dict for a brand-new session -- callers
    should pass this as the FIRST invocation's input; every later
    invocation should instead build a minimal per-event input (see
    `InterviewAgentService.handle_trigger`'s docstring) so the
    checkpointer's persisted state carries forward correctly."""
    return InterviewGraphState(
        session_id=str(session_id), tenant_id=str(tenant_id) if tenant_id else None,
        candidate_user_id=str(candidate_user_id) if candidate_user_id else None,
        interviewer_ids=[str(i) for i in interviewer_ids],
        phase="WAITING", phase_history=[], pending_phase=None,
        trigger=None, trigger_payload={},
        current_code="", current_language="", code_snapshot_ids=[], last_meaningful_diff="",
        current_question=None, question_history=[], suggested_question=None, human_approved_question=False,
        code_analysis_results=[], integrity_signals=[], copilot_suggestions=[],
        guardrail_log=[], last_guardrail_action=None,
        awaiting_human_approval=False, human_approval_type=None, human_decision=None,
        scorecard=None, scorecard_approved=False,
        fallback_reason=None,
    )


def build_interview_graph(
    *,
    guardrail_service: GuardrailService,
    code_analysis_llm_call: CodeAnalysisLLMCallFn,
    copilot_llm_call: NarrativeLLMCallFn,
    report_synthesis_llm_call: CodeAnalysisLLMCallFn,
    question_pool_provider: Callable[[InterviewGraphState], list[CandidateQuestion]] | None = None,
):
    """Compiles Graph 1. `question_pool_provider` supplies the
    in-memory candidate-question list `rag_question_retrieval_tool`
    ranks against (interim stand-in -- see that tool's docstring);
    defaults to an empty pool (no questions available) if omitted."""

    question_pool_provider = question_pool_provider or (lambda state: [])

    # ── input_guardrail_node ─────────────────────────────────────────
    async def input_guardrail_node(state: InterviewGraphState) -> dict:
        """Layer 1 on whatever candidate-originated text this
        invocation carries: the code diff (CODE_DIFF_MEANINGFUL) or raw
        integrity payload text (INTEGRITY_EVENT). Other triggers carry
        no fresh candidate text -- nothing to sanitize."""
        trigger = state.get("trigger")
        tenant_id = uuid.UUID(state["tenant_id"]) if state["tenant_id"] else None
        session_id = uuid.UUID(state["session_id"])

        candidate_text = ""
        if trigger == "CODE_DIFF_MEANINGFUL":
            candidate_text = state.get("last_meaningful_diff") or state.get("current_code") or ""
        elif trigger == "INTEGRITY_EVENT":
            candidate_text = str(state.get("trigger_payload", {}).get("raw_signal_data", ""))

        if not candidate_text:
            return {}

        result = await guardrail_service.validate_input(
            agent_name=AGENT_CODE_ANALYSIS if trigger == "CODE_DIFF_MEANINGFUL" else AGENT_INTEGRITY,
            text=candidate_text, tenant_id=tenant_id, session_id=session_id, trace_id=state["session_id"],
        )
        if result.action == "BLOCKED":
            fallback = await guardrail_service.trigger_fallback(
                agent_name="input_guardrail", reason=f"input guardrail blocked: {result.block_reason}",
                tenant_id=tenant_id, session_id=session_id,
            )
            return {"last_guardrail_action": "BLOCKED", "fallback_reason": fallback.reason}
        return {}

    def _route_after_input_guardrail(state: InterviewGraphState) -> Literal["continue", "fallback"]:
        return "fallback" if state.get("fallback_reason") else "continue"

    # ── orchestrator_node ────────────────────────────────────────────
    async def orchestrator_node(state: InterviewGraphState) -> dict:
        """Deterministic routing only (Section: "I can point to exactly
        which orchestrator routing decisions are deterministic vs
        model-driven") -- reads `trigger`, sets `pending_phase` for a
        PHASE_TRANSITION trigger. No LLM call happens here.

        Also resets the transient per-invocation flags
        (`fallback_reason`, and any stale `awaiting_human_approval`/
        `human_approval_type` left over from a PRIOR invocation that
        never got resumed/cleared -- see `integrity_node`'s docstring
        for the one case, INTEGRITY_REVIEW, that sets this flag without
        an actual graph pause). This node is the entry point for every
        fresh trigger invocation (never re-run on a resume, since
        LangGraph resumes directly at the paused node), so this is the
        correct single place to clear stale state before routing."""
        update: dict[str, Any] = {"fallback_reason": None}
        if state.get("human_approval_type") == "INTEGRITY_REVIEW":
            update["awaiting_human_approval"] = False
            update["human_approval_type"] = None
        if state.get("trigger") == "PHASE_TRANSITION":
            next_phase = state.get("trigger_payload", {}).get("next_phase")
            update["pending_phase"] = next_phase
        return update

    def _route_orchestrator(state: InterviewGraphState) -> list[str]:
        """Section: orchestrator routes to the specific handler for
        `trigger` AND, "always", fans out to `copilot_node` in
        parallel. LangGraph's conditional-edge `path` function can
        return a sequence of destination keys to fan out to multiple
        nodes from one call -- this is that fan-out, done as ONE
        conditional-edges registration (calling `add_conditional_edges`
        twice from the same source node overwrites the first
        registration rather than adding to it, so both destinations
        must come from a single routing function)."""
        if state.get("phase") == "WAITING" and state.get("trigger") != "PHASE_TRANSITION":
            return ["end"]

        trigger = state.get("trigger")
        destinations = [_INTERVIEW_TRIGGER_TO_NODE.get(trigger, "end")]

        # Co-Pilot only has something useful to say once there's a
        # session in progress and at least one code analysis result to
        # react to (or this invocation is itself producing one).
        has_prior_analysis = bool(state.get("code_analysis_results"))
        if trigger == "CODE_DIFF_MEANINGFUL" or has_prior_analysis:
            destinations.append("copilot_node")

        return destinations

    # ── code_analysis_node ───────────────────────────────────────────
    async def code_analysis_node(state: InterviewGraphState) -> dict:
        tenant_id = uuid.UUID(state["tenant_id"]) if state["tenant_id"] else None
        session_id = uuid.UUID(state["session_id"])
        code = state.get("last_meaningful_diff") or state.get("current_code") or ""

        # Tools: sandbox (mocked, flagged) + complexity analysis (rule-based).
        current_question = state.get("current_question") or {}
        test_cases = current_question.get("test_cases") if isinstance(current_question, dict) else None
        sandbox_result = run_in_sandbox(code=code, language=state.get("current_language", ""), test_cases=test_cases)
        complexity_result = analyze_complexity(code=code, language=state.get("current_language", ""))

        async def llm_call(prompt: str) -> dict[str, Any]:
            raw = await code_analysis_llm_call(prompt)
            # The tools' deterministic output always wins over anything
            # the LLM claims for these two fields (Rule 2.2: "trust
            # sandbox results over LLM narrative").
            raw = dict(raw)
            raw["passed_tests"] = sandbox_result.passed_tests
            raw["failed_tests"] = sandbox_result.failed_tests
            raw.setdefault("complexity_estimate", complexity_result.time_complexity_estimate)
            raw.setdefault("style_issues", complexity_result.style_issues)
            return raw

        result = await run_guarded_agent_node(
            guardrail_service=guardrail_service, agent_name=AGENT_CODE_ANALYSIS, node_name="code_analysis_node",
            candidate_text=code, schema_model=CodeAnalysisResult, llm_call=llm_call,
            sandbox_passed_tests=sandbox_result.passed_tests, tenant_id=tenant_id, session_id=session_id,
            trace_id=state["session_id"],
        )

        if isinstance(result, FallbackDecision):
            return {"last_guardrail_action": "BLOCKED", "fallback_reason": result.reason}

        analysis_dict = result.model_dump(mode="json")
        return {
            "code_analysis_results": state["code_analysis_results"] + [analysis_dict],
            "last_guardrail_action": "PASSED",
        }

    # ── question_strategist_node ─────────────────────────────────────
    async def question_strategist_node(state: InterviewGraphState) -> dict:
        """Deterministic (tool-based, no LLM) per this milestone's
        interim `rag_question_retrieval_tool` -- see that tool's
        docstring. Routes to human_approval_node (QUESTION) on success;
        no candidate-originated free text is involved here (the
        candidate never supplies topic_tags/difficulty), so there is no
        Layer-1 sanitization step for this node specifically."""
        correctness_values = [r["correctness_pct"] for r in state["code_analysis_results"]]
        current_difficulty = None
        if state.get("current_question") and isinstance(state["current_question"], dict):
            current_difficulty = state["current_question"].get("difficulty")

        calibration = calibrate_difficulty(correctness_percentages=correctness_values, current_difficulty=current_difficulty)

        pool = question_pool_provider(state)
        exclude_ids = [q["question_id"] for q in state["question_history"] if isinstance(q, dict) and "question_id" in q]
        topic_tags = state.get("trigger_payload", {}).get("topic_tags", [])
        ranked = retrieve_candidate_questions(
            difficulty_target=calibration.recommended_difficulty, topic_tags=topic_tags,
            exclude_ids=exclude_ids, question_pool=pool, top_k=1,
        )

        if not ranked:
            fallback = await guardrail_service.trigger_fallback(
                agent_name=AGENT_QUESTION_STRATEGIST, reason="no candidate questions available in the pool",
                tenant_id=uuid.UUID(state["tenant_id"]) if state["tenant_id"] else None,
                session_id=uuid.UUID(state["session_id"]),
            )
            return {"last_guardrail_action": "BLOCKED", "fallback_reason": fallback.reason}

        chosen, score = ranked[0]
        suggested = SuggestedQuestion(
            question_id=uuid.uuid4(), title=chosen.title, body=chosen.body, difficulty=chosen.difficulty,
            rationale=f"Similarity score {score:.2f} to requested topics; {calibration.rationale}",
            topic_tags=chosen.topic_tags, difficulty_rationale=calibration.rationale,
        )

        output_result = await guardrail_service.validate_output(
            agent_name=AGENT_QUESTION_STRATEGIST, raw_output=suggested.model_dump(mode="json"),
            schema_model=SuggestedQuestion, tenant_id=uuid.UUID(state["tenant_id"]) if state["tenant_id"] else None,
            session_id=uuid.UUID(state["session_id"]), trace_id=state["session_id"],
        )
        if output_result.action == "BLOCKED":
            fallback = await guardrail_service.trigger_fallback(
                agent_name=AGENT_QUESTION_STRATEGIST, reason=f"output guardrail blocked: {output_result.block_reason}",
                tenant_id=uuid.UUID(state["tenant_id"]) if state["tenant_id"] else None,
                session_id=uuid.UUID(state["session_id"]),
            )
            return {"last_guardrail_action": "BLOCKED", "fallback_reason": fallback.reason}

        return {
            "suggested_question": output_result.validated_output.model_dump(mode="json"),
            "awaiting_human_approval": True, "human_approval_type": "QUESTION", "last_guardrail_action": "PASSED",
        }

    # ── integrity_node ───────────────────────────────────────────────
    async def integrity_node(state: InterviewGraphState) -> dict:
        """Rule-based/lightweight-classifier only -- Section: "DOES NOT
        call an LLM ... The LLM is only used for stylometric drift
        analysis." This milestone does not implement the stylometric
        drift LLM call (no session baseline data source exists yet) --
        every signal here comes straight from the client-reported
        event, validated (never a field named verdict/recommendation --
        Rule 2.4) and appended."""
        payload = state.get("trigger_payload", {})
        tenant_id = uuid.UUID(state["tenant_id"]) if state["tenant_id"] else None
        session_id = uuid.UUID(state["session_id"])

        raw_signal = {
            "signal_type": payload.get("event_type", "unknown"),
            "confidence_score": float(payload.get("confidence_score", 0.5)),
            "raw_evidence": str(payload.get("raw_signal_data", "")),
            "session_id": str(session_id),
        }

        output_result = await guardrail_service.validate_output(
            agent_name=AGENT_INTEGRITY, raw_output=raw_signal, schema_model=IntegritySignal,
            tenant_id=tenant_id, session_id=session_id, trace_id=state["session_id"],
        )
        if output_result.action == "BLOCKED":
            fallback = await guardrail_service.trigger_fallback(
                agent_name=AGENT_INTEGRITY, reason=f"output guardrail blocked: {output_result.block_reason}",
                tenant_id=tenant_id, session_id=session_id,
            )
            return {"last_guardrail_action": "BLOCKED", "fallback_reason": fallback.reason}

        should_escalate = await guardrail_service.record_integrity_signal(session_id=session_id, tenant_id=tenant_id)

        update: dict[str, Any] = {
            "integrity_signals": state["integrity_signals"] + [output_result.validated_output.model_dump(mode="json")],
            "last_guardrail_action": "PASSED",
        }
        if should_escalate:
            # Rule 5.4: "escalate ... Human interviewer must explicitly
            # decide to continue or end session." NOTE: this does NOT
            # route through a LangGraph interrupt the way the question/
            # scorecard approvals do -- integrity_node's own edge goes
            # straight to END (see graph wiring below), so
            # `awaiting_human_approval`/`human_approval_type` here are
            # an OUTPUT SIGNAL ONLY for the caller (interview_service's
            # WebSocket gateway shows the interviewer a persistent
            # "N integrity signals -- continue or end session?" alert
            # over the `agent_event` channel, Slice 2's job). The
            # interviewer's actual decision is made through the
            # session's EXISTING controls -- M9's `end_session` message
            # to end it, or simply continuing normally -- not by
            # resuming this graph. `orchestrator_node` clears this flag
            # at the start of the next invocation once the interviewer
            # has had a chance to see it (see that node's docstring),
            # so it never goes permanently stale.
            update["awaiting_human_approval"] = True
            update["human_approval_type"] = "INTEGRITY_REVIEW"
        return update

    # ── copilot_node ─────────────────────────────────────────────────
    async def copilot_node(state: InterviewGraphState) -> dict:
        tenant_id = uuid.UUID(state["tenant_id"]) if state["tenant_id"] else None
        session_id = uuid.UUID(state["session_id"])

        context_text = (
            f"Recent code analysis results: {state['code_analysis_results'][-3:]}\n"
            f"Question history: {state['question_history']}\n"
        )

        async def llm_call(prompt: str) -> dict[str, Any]:
            text = await copilot_llm_call(prompt)
            return {"suggested_followup": text, "confidence": 0.6, "based_on": ["code_analysis_results"]}

        result = await run_guarded_agent_node(
            guardrail_service=guardrail_service, agent_name=AGENT_COPILOT, node_name="copilot_node",
            candidate_text=context_text, schema_model=CoPilotSuggestion, llm_call=llm_call,
            tenant_id=tenant_id, session_id=session_id, trace_id=state["session_id"],
        )
        if isinstance(result, FallbackDecision):
            # Rule 5.1: Co-Pilot going down never blocks the session --
            # just no suggestion this round.
            return {}
        return {"copilot_suggestions": state["copilot_suggestions"] + [result.model_dump(mode="json")]}

    # ── report_synthesis_node ────────────────────────────────────────
    async def report_synthesis_node(state: InterviewGraphState) -> dict:
        tenant_id = uuid.UUID(state["tenant_id"]) if state["tenant_id"] else None
        session_id = uuid.UUID(state["session_id"])

        transcript = fetch_session_transcript(session_id=session_id)
        # See fetch_session_transcript_tool.py -- always unavailable
        # until FIX-M9 adds chat persistence. report_synthesis proceeds
        # on code history + integrity signals + question history alone.

        history_text = (
            f"Code analysis results: {state['code_analysis_results']}\n"
            f"Question history: {state['question_history']}\n"
            f"Integrity signal count: {len(state['integrity_signals'])}\n"
            f"Transcript available: {transcript.available}"
        )

        async def llm_call(prompt: str) -> dict[str, Any]:
            raw = await report_synthesis_llm_call(prompt)
            raw = dict(raw)
            raw.setdefault("session_id", str(session_id))
            raw.setdefault("integrity_summary", {"signals_count": len(state["integrity_signals"])})
            return raw

        result = await run_guarded_agent_node(
            guardrail_service=guardrail_service, agent_name=AGENT_REPORT_SYNTHESIS, node_name="report_synthesis_node",
            candidate_text=history_text, schema_model=Scorecard, llm_call=llm_call,
            tenant_id=tenant_id, session_id=session_id, trace_id=state["session_id"],
        )
        if isinstance(result, FallbackDecision):
            return {"last_guardrail_action": "BLOCKED", "fallback_reason": result.reason}

        # Layer 4 -- PII redaction, scoped to Report Synthesis output only.
        pii_result = await guardrail_service.pii_scan(result, tenant_id=tenant_id, trace_id=state["session_id"])
        redacted: Scorecard = pii_result.redacted_output

        return {
            "scorecard": redacted.model_dump(mode="json"), "awaiting_human_approval": True,
            "human_approval_type": "SCORECARD", "last_guardrail_action": "PASSED",
        }

    # ── human_approval_node (interrupt #1 / #2) ──────────────────────
    async def human_approval_node(state: InterviewGraphState) -> dict:
        """Runs on RESUME, after `human_decision` has been set by
        `InterviewAgentService.resume_after_human_decision()` via
        `graph.aupdate_state()` (the exact pattern `ranking_graph.py`'s
        `human_approval_node` + `RankingAgentService.resume_after_human_decision`
        already established). Section 5.3: a REJECTED question re-routes
        to `question_strategist_node` -- per this graph's one-invocation-
        per-event design, "re-route" means the caller issues a fresh
        QUESTION_REQUEST trigger on its next invocation; this node just
        clears the rejected suggestion so a stale one is never reused."""
        approval_type = state.get("human_approval_type")
        decision = state.get("human_decision")

        if approval_type == "QUESTION":
            if decision in ("APPROVED", "EDITED"):
                approved_question = state.get("suggested_question")
                return {
                    "human_approved_question": True, "current_question": approved_question,
                    "question_history": state["question_history"] + ([approved_question] if approved_question else []),
                    "suggested_question": None, "awaiting_human_approval": False,
                    "human_approval_type": None, "human_decision": None,
                }
            # REJECTED, or no decision arrived within the 60s window
            # (Rule 5.3: "auto-dismisses suggestion ... session is NOT
            # blocked") -- both clear the pending suggestion.
            return {
                "suggested_question": None, "human_approved_question": False, "awaiting_human_approval": False,
                "human_approval_type": None, "human_decision": None,
            }

        if approval_type == "SCORECARD":
            if decision == "APPROVED":
                scorecard = dict(state["scorecard"]) if state.get("scorecard") else None
                if scorecard is not None:
                    scorecard["is_final"] = True
                return {
                    "scorecard": scorecard, "scorecard_approved": True, "awaiting_human_approval": False,
                    "human_approval_type": None, "human_decision": None,
                }
            # Rule 5.3: "scorecard approval waits indefinitely (no
            # auto-approval ever)" -- a decision other than APPROVED
            # (including None, i.e. no decision yet) never finalizes it.
            return {
                "scorecard_approved": False, "awaiting_human_approval": False,
                "human_approval_type": None, "human_decision": None,
            }

        # NOTE: approval_type == "INTEGRITY_REVIEW" never reaches this
        # node -- `integrity_node` routes straight to END (see graph
        # wiring); that flag is an output signal only, cleared by
        # `orchestrator_node` at the start of the next invocation. See
        # `integrity_node`'s docstring for the full explanation.
        return {"awaiting_human_approval": False, "human_approval_type": None, "human_decision": None}

    # ── phase_transition_node (interrupt #3) ─────────────────────────
    async def phase_transition_node(state: InterviewGraphState) -> dict:
        """Runs on RESUME after the interviewer confirms (or the 5-min
        timeout policy marks a persistent alert -- Rule 5.3). Prevents
        accidental phase jumps during a live session (Section)."""
        decision = state.get("human_decision")
        pending_phase = state.get("pending_phase")

        if decision == "CONFIRMED" and pending_phase:
            transition = {
                "from": state["phase"], "to": pending_phase,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            return {
                "phase": pending_phase, "phase_history": state["phase_history"] + [transition],
                "pending_phase": None, "human_decision": None,
            }
        # Not confirmed (or timed out) -- stays in the current phase.
        # Rule 5.3's "persistent alert" is a UI/notification concern
        # for the caller (interview_service), not graph state.
        return {"pending_phase": None, "human_decision": None}

    # ── fallback_node ────────────────────────────────────────────────
    async def fallback_node(state: InterviewGraphState) -> dict:
        """Rule 5.1: never crashes the session, never surfaces the
        error to the candidate. `fallback_reason` is already set by
        whichever node routed here -- this node's only job is to make
        sure the invocation ends cleanly with that reason visible to
        the caller (who is responsible for showing the interviewer
        the 'AI suggestions temporarily unavailable' notice, per M9's
        `ws_gateway.py` `agent_event` channel -- Slice 2's job)."""
        return {"last_guardrail_action": "BLOCKED"}

    def _route_after_agent_node(state: InterviewGraphState) -> Literal["approval", "fallback", "end"]:
        if state.get("fallback_reason"):
            return "fallback"
        if state.get("awaiting_human_approval") and state.get("human_approval_type") in ("QUESTION", "SCORECARD"):
            return "approval"
        return "end"

    graph = StateGraph(InterviewGraphState)
    graph.add_node("input_guardrail_node", input_guardrail_node)
    graph.add_node("orchestrator_node", orchestrator_node)
    graph.add_node("code_analysis_node", code_analysis_node)
    graph.add_node("question_strategist_node", question_strategist_node)
    graph.add_node("integrity_node", integrity_node)
    graph.add_node("copilot_node", copilot_node)
    graph.add_node("report_synthesis_node", report_synthesis_node)
    graph.add_node("human_approval_node", human_approval_node)
    graph.add_node("phase_transition_node", phase_transition_node)
    graph.add_node("fallback_node", fallback_node)

    graph.set_entry_point("input_guardrail_node")
    graph.add_conditional_edges(
        "input_guardrail_node", _route_after_input_guardrail, {"continue": "orchestrator_node", "fallback": "fallback_node"}
    )
    # Single conditional-edges registration whose path function returns
    # a LIST of destination keys, so orchestrator_node can fan out to
    # BOTH the trigger-specific handler AND copilot_node in the same
    # step (Section: "always -> [copilot_node] (runs in parallel)") --
    # see `_route_orchestrator`'s docstring for why this must be one
    # call, not two.
    graph.add_conditional_edges(
        "orchestrator_node", _route_orchestrator,
        {
            "code_analysis_node": "code_analysis_node", "question_strategist_node": "question_strategist_node",
            "integrity_node": "integrity_node", "phase_transition_node": "phase_transition_node",
            "report_synthesis_node": "report_synthesis_node", "copilot_node": "copilot_node", "end": END,
        },
    )

    graph.add_conditional_edges("code_analysis_node", _route_after_agent_node, {"approval": "human_approval_node", "fallback": "fallback_node", "end": END})
    graph.add_conditional_edges("question_strategist_node", _route_after_agent_node, {"approval": "human_approval_node", "fallback": "fallback_node", "end": END})
    graph.add_conditional_edges("report_synthesis_node", _route_after_agent_node, {"approval": "human_approval_node", "fallback": "fallback_node", "end": END})
    graph.add_edge("integrity_node", END)
    graph.add_edge("copilot_node", END)
    graph.add_edge("human_approval_node", END)
    graph.add_edge("phase_transition_node", END)
    graph.add_edge("fallback_node", END)

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer, interrupt_before=["human_approval_node", "phase_transition_node"])