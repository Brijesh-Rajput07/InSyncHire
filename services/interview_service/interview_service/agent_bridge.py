# LOCATION: services/interview_service/interview_service/agent_bridge.py

"""
M10 Slice 2 -- the bridge between `interview_service`'s WebSocket
gateway (M9) and `agent_service`'s Graph 1 (M10 Slice 1).

*** ARCHITECTURAL DECISION: in-process import, not HTTP -- see the
handoff response's explanation for the full reasoning. *** Every
cross-service interaction built so far in this codebase is either a
shared LIBRARY import (`insynchire-events`, `auth-tokens`,
`permissions`) or an async KAFKA EVENT -- never a synchronous
cross-service HTTP call. Agent Service has no HTTP surface at all
(Section 6 lists no `routes/` for it). Standing one up is a real design
decision on its own (auth scheme, request/response schemas, a FastAPI
app) that shouldn't be a silent side effect of wiring M9's gateway to
Graph 1. So for M10 Slice 2, `interview_service` depends on the
`agent_service` PACKAGE directly (added as a normal Python dependency
in `pyproject.toml`) and calls `InterviewAgentService` in-process.

This module is the ENTIRE surface of that dependency -- nothing else in
`interview_service` imports `agent_service` directly. When Agent
Service needs to scale independently (real LLM calls get slow/expensive
enough to warrant a separate deployable, or multiple services need to
call it), this file is where an HTTP client replaces the in-process
`InterviewAgentService` call -- `ws_gateway.py` never needs to change,
since it only ever talks to this module's `AgentBridge` class.

*** NO REAL LLM PROVIDER IS WIRED IN -- PLACEHOLDER FUNCTIONS, FLAGGED ***
There is no Anthropic/OpenAI/etc. client anywhere in this codebase yet
(M6's own README says the same thing about NeMo Guardrails: "wire in
for real once a live LLM call exists"). The three LLM-calling functions
below (`_placeholder_code_analysis_llm_call`, `_placeholder_copilot_llm_call`,
`_placeholder_report_synthesis_llm_call`) are clearly-labeled stand-ins
that let Graph 1 run end-to-end (guardrails, sandbox/complexity tools,
human-in-the-loop interrupts, code snapshot persistence trigger) without
pretending an LLM produced the narrative content. Wiring a real
provider is a separate, explicitly-scoped follow-up task -- swap these
three functions' bodies for real API calls and nothing else in this
module or `ws_gateway.py` needs to change.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent_service.guardrails import GuardrailService
from agent_service.services import InterviewAgentService, InterviewTriggerResult
from agent_service.tools import CandidateQuestion


# ─────────────────────────────────────────────────────────────────────
# Debouncing (Section: "last_meaningful_diff — debounced — not every
# keystroke")
# ─────────────────────────────────────────────────────────────────────

@dataclass
class CodeUpdateDebouncer:
    """Decides whether a `code_update` WebSocket message is "meaningful"
    enough to trigger `code_analysis_node`, rather than firing on every
    keystroke (which would make the Rule 5.2 circuit breaker trip
    almost immediately, and would be a poor interviewer experience --
    a new Co-Pilot suggestion after every character typed).

    Two independent conditions, either of which is enough:
      1. At least `min_interval_seconds` have passed since the last
         triggered analysis for this session.
      2. The code has grown/shrunk by at least `min_char_delta`
         characters since the last triggered analysis.

    Purely in-memory, keyed by session_id -- matches the same
    "Redis-shaped interface, in-memory for now" precedent
    `agent_service.guardrails.behavioral_guardrails.CircuitBreaker`
    already established (a horizontally-scaled Interview Service would
    need this backed by Redis, same documented gap as M9's
    `InProcessBroadcaster`).
    """

    min_interval_seconds: float = 3.0
    min_char_delta: int = 20
    _last_triggered_at: dict[str, float] = field(default_factory=dict)
    _last_triggered_code: dict[str, str] = field(default_factory=dict)

    def should_trigger(self, *, session_id: uuid.UUID | str, current_code: str, now: float | None = None) -> bool:
        key = str(session_id)
        now = now if now is not None else time.monotonic()

        last_at = self._last_triggered_at.get(key)
        last_code = self._last_triggered_code.get(key, "")

        if last_at is None:
            return True

        elapsed = now - last_at
        char_delta = abs(len(current_code) - len(last_code))

        return elapsed >= self.min_interval_seconds or char_delta >= self.min_char_delta

    def record_trigger(self, *, session_id: uuid.UUID | str, code: str, now: float | None = None) -> None:
        key = str(session_id)
        self._last_triggered_at[key] = now if now is not None else time.monotonic()
        self._last_triggered_code[key] = code

    def reset(self, session_id: uuid.UUID | str) -> None:
        key = str(session_id)
        self._last_triggered_at.pop(key, None)
        self._last_triggered_code.pop(key, None)


# ─────────────────────────────────────────────────────────────────────
# Placeholder LLM calls -- see module docstring
# ─────────────────────────────────────────────────────────────────────

async def _placeholder_code_analysis_llm_call(prompt: str) -> dict[str, Any]:
    """PLACEHOLDER. Returns a neutral, non-extreme correctness estimate
    (50.0) so Rule 2.2's sandbox-vs-LLM consistency check (which only
    fires when the LLM claims >80% correctness while the sandbox saw
    zero passing tests) doesn't spuriously trip just because this
    placeholder has no real basis for its number. Replace with a real
    LLM call that actually reads the <candidate_data>-wrapped code and
    test results."""
    return {"correctness_pct": 50.0}


async def _placeholder_copilot_llm_call(prompt: str) -> str:
    """PLACEHOLDER. A real Co-Pilot node would read the wrapped
    candidate context and produce a genuine follow-up question or
    hint. This returns a fixed, clearly-generic message so the
    `agent_event` plumbing (M9) has something real to carry until a
    real LLM is wired in."""
    return "No AI suggestion available yet -- LLM provider not configured for this deployment."


async def _placeholder_report_synthesis_llm_call(prompt: str) -> dict[str, Any]:
    """PLACEHOLDER. Full Report Synthesis Agent wiring (the scorecard
    approval workflow, PDF export, and `scorecard.generated` Kafka
    publish) is explicitly Milestone M11's job (Section 4 build order:
    "M11 | Report Synthesis Agent + scorecard approval + PDF export").
    This placeholder exists only so Graph 1's `report_synthesis_node`
    doesn't crash if a SESSION_COMPLETED trigger reaches it during
    Slice 2 testing -- M11 should replace this with the real agent."""
    return {
        "dimensions": {},
        "overall_summary": "Scorecard generation is not yet configured for this deployment.",
        "overall_recommendation": "NO",
        "recommendation_rationale": "Placeholder -- see agent_bridge.py module docstring; full wiring is M11's job.",
    }


# ─────────────────────────────────────────────────────────────────────
# AgentBridge -- what ws_gateway.py actually calls
# ─────────────────────────────────────────────────────────────────────

class AgentBridge:
    """Owns one `InterviewAgentService` (and therefore one compiled
    Graph 1) for the whole process, plus the debouncer. Constructed
    once at startup (`dependencies.py`), injected into `ws_gateway.py`
    the same way `SessionConnectionRegistry`/`InProcessBroadcaster` are.
    """

    def __init__(
        self,
        *,
        guardrail_service: GuardrailService | None = None,
        question_pool_provider=None,
        debouncer: CodeUpdateDebouncer | None = None,
    ):
        self.guardrail_service = guardrail_service or GuardrailService()
        self.debouncer = debouncer or CodeUpdateDebouncer()
        self._interview_agent_service = InterviewAgentService(
            guardrail_service=self.guardrail_service,
            code_analysis_llm_call=_placeholder_code_analysis_llm_call,
            copilot_llm_call=_placeholder_copilot_llm_call,
            report_synthesis_llm_call=_placeholder_report_synthesis_llm_call,
            question_pool_provider=question_pool_provider,
        )

    async def maybe_trigger_code_analysis(
        self, *, session_id: uuid.UUID, tenant_id: uuid.UUID | None, candidate_user_id: uuid.UUID | None,
        interviewer_ids: list[uuid.UUID], phase: str, current_code: str, current_language: str,
        current_question: dict | None = None,
    ) -> InterviewTriggerResult | None:
        """Called from `ws_gateway.py`'s `code_update` handler AFTER it
        persists the snapshot (M9's existing behavior is unchanged --
        this is purely additive). Returns None (does nothing) if the
        debouncer decides this update isn't meaningful yet."""
        if not self.debouncer.should_trigger(session_id=session_id, current_code=current_code):
            return None
        self.debouncer.record_trigger(session_id=session_id, code=current_code)

        return await self._interview_agent_service.handle_trigger(
            session_id=session_id, tenant_id=tenant_id, candidate_user_id=candidate_user_id,
            interviewer_ids=interviewer_ids, phase=phase, trigger="CODE_DIFF_MEANINGFUL",
            last_meaningful_diff=current_code, current_language=current_language,
            current_question=current_question,
        )

    async def trigger_integrity_event(
        self, *, session_id: uuid.UUID, tenant_id: uuid.UUID | None, candidate_user_id: uuid.UUID | None,
        interviewer_ids: list[uuid.UUID], phase: str, event_type: str, confidence_score: float,
        raw_signal_data: str,
    ) -> InterviewTriggerResult:
        """Called from a NEW `integrity_event` WebSocket message
        (Section: "triggered by client-side events (tab-switch,
        paste-burst) forwarded by Interview Service"). Any connection
        may send one (typically the candidate's client, which is where
        tab-switch/paste-burst detection actually runs) -- the result
        is only ever broadcast to `interviewer`-role connections by
        `ws_gateway.py`, never back to the sender."""
        return await self._interview_agent_service.handle_trigger(
            session_id=session_id, tenant_id=tenant_id, candidate_user_id=candidate_user_id,
            interviewer_ids=interviewer_ids, phase=phase, trigger="INTEGRITY_EVENT",
            trigger_payload={"event_type": event_type, "confidence_score": confidence_score, "raw_signal_data": raw_signal_data},
        )

    async def trigger_question_request(
        self, *, session_id: uuid.UUID, tenant_id: uuid.UUID | None, candidate_user_id: uuid.UUID | None,
        interviewer_ids: list[uuid.UUID], phase: str, topic_tags: list[str] | None = None,
        current_question: dict | None = None,
    ) -> InterviewTriggerResult:
        """Called from a NEW `question_request` WebSocket message,
        staff-only (interviewer/recruiter/company_admin) -- see
        `ws_gateway.py`'s role check. Always ends with
        `awaiting_human_approval=True` (or a fallback if no questions
        are available), never auto-injects a question."""
        return await self._interview_agent_service.handle_trigger(
            session_id=session_id, tenant_id=tenant_id, candidate_user_id=candidate_user_id,
            interviewer_ids=interviewer_ids, phase=phase, trigger="QUESTION_REQUEST",
            trigger_payload={"topic_tags": topic_tags or []}, current_question=current_question,
        )

    async def trigger_phase_transition_request(
        self, *, session_id: uuid.UUID, tenant_id: uuid.UUID | None, candidate_user_id: uuid.UUID | None,
        interviewer_ids: list[uuid.UUID], phase: str, next_phase: str,
    ) -> InterviewTriggerResult:
        """Called from a NEW `phase_transition_request` WebSocket
        message, staff-only. Always pauses at `phase_transition_node`
        (Section: "Prevents accidental phase jumps during live
        session") -- the phase never actually changes until a
        `human_decision` message with `decision="CONFIRMED"` resumes it."""
        return await self._interview_agent_service.handle_trigger(
            session_id=session_id, tenant_id=tenant_id, candidate_user_id=candidate_user_id,
            interviewer_ids=interviewer_ids, phase=phase, trigger="PHASE_TRANSITION",
            trigger_payload={"next_phase": next_phase},
        )

    async def resume_human_decision(self, *, session_id: uuid.UUID, decision: str) -> InterviewTriggerResult:
        """Called from a NEW `human_decision` WebSocket message,
        staff-only. `decision` is one of APPROVED/EDITED/REJECTED
        (question or scorecard) or CONFIRMED (phase transition) -- the
        client is responsible for sending the right one, since it's the
        one that was shown the corresponding prompt over `agent_event`."""
        return await self._interview_agent_service.resume_after_human_decision(session_id=session_id, decision=decision)

    async def get_state(self, session_id: uuid.UUID) -> dict | None:
        return await self._interview_agent_service.get_state(session_id)


def build_default_question_pool_provider(pool: list[CandidateQuestion]):
    """Convenience factory for a static in-memory question pool (the
    interim `rag_question_retrieval_tool` stand-in, M10 Slice 1) --
    a real deployment would instead build a provider that reads the
    tenant's actual `question_bank` rows once that table exists."""
    return lambda state: pool