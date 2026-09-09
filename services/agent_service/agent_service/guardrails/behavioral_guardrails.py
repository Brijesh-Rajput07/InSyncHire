# LOCATION: services/agent_service/agent_service/guardrails/behavioral_guardrails.py

"""
LAYER 5 -- BEHAVIORAL / FALLBACK GUARDRAILS (Section: GUARDRAILS ARCHITECTURE).

Rule 5.1 -- Agent failure graceful degradation (fallback_node, never
            crashes the session, never surfaces the error to the candidate)
Rule 5.2 -- Orchestrator loop prevention (circuit breaker: >5 triggers
            in 60s on the same node -> trip for 5 minutes)
Rule 5.3 -- Human-in-the-loop timeout handling (helpers describing the
            three named timeout behaviors; the actual 60s/5min timers
            live in the LangGraph interrupt nodes built in M10 -- this
            module provides the decision logic those nodes call)
Rule 5.4 -- Integrity flag escalation (>5 signals in 30 minutes for the
            same session -> escalate to human_approval_node)

`CircuitBreaker` and `IntegrityEscalationTracker` hold in-memory state
keyed by (tenant_id, node/session identifiers) -- Redis-backed
persistence (matching Section: "Redis with session_id key" for
LangGraph checkpoints) is a straightforward drop-in swap for a later
milestone once this service has a live Redis connection; the interface
here is deliberately Redis-shaped (get/record/is-tripped) so that swap
doesn't change any calling code.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field

from ..schemas.guardrail_schemas import FallbackDecision, GuardrailCheckResult

LAYER = 5


class CircuitBreaker:
    """Rule 5.2. Tracks trigger timestamps per `node_key` (typically
    f"{tenant_id}:{session_id}:{node_name}") in a sliding window. If the
    same node triggers more than `max_triggers` times within
    `window_seconds` (without what the orchestrator considers a
    meaningful state change -- that judgment stays with the caller;
    this class just counts triggers), the breaker trips for
    `cooldown_seconds`."""

    def __init__(self, *, max_triggers: int, window_seconds: float, cooldown_seconds: float):
        self._max_triggers = max_triggers
        self._window_seconds = window_seconds
        self._cooldown_seconds = cooldown_seconds
        self._trigger_times: dict[str, deque[float]] = defaultdict(deque)
        self._tripped_until: dict[str, float] = {}

    def is_tripped(self, node_key: str, *, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        tripped_until = self._tripped_until.get(node_key)
        if tripped_until is None:
            return False
        if now >= tripped_until:
            del self._tripped_until[node_key]
            return False
        return True

    def record_trigger(self, node_key: str, *, now: float | None = None) -> bool:
        """Records one trigger; returns True if this call caused the
        breaker to trip (i.e. the (max_triggers+1)th trigger within the
        window)."""
        now = now if now is not None else time.monotonic()
        window = self._trigger_times[node_key]
        window.append(now)
        cutoff = now - self._window_seconds
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) > self._max_triggers:
            self._tripped_until[node_key] = now + self._cooldown_seconds
            return True
        return False

    def reset(self, node_key: str) -> None:
        """Called on a genuine meaningful state change -- clears the
        node's trigger history so unrelated activity doesn't count
        toward tripping the breaker."""
        self._trigger_times.pop(node_key, None)
        self._tripped_until.pop(node_key, None)


class IntegrityEscalationTracker:
    """Rule 5.4. Tracks `IntegritySignal` occurrences per session_id in
    a sliding window; once more than `max_signals` land within
    `window_seconds`, escalation is required."""

    def __init__(self, *, max_signals: int, window_seconds: float):
        self._max_signals = max_signals
        self._window_seconds = window_seconds
        self._signal_times: dict[str, deque[float]] = defaultdict(deque)

    def record_signal(self, session_id: str, *, now: float | None = None) -> bool:
        """Returns True if this signal pushed the session over the
        escalation threshold."""
        now = now if now is not None else time.monotonic()
        window = self._signal_times[session_id]
        window.append(now)
        cutoff = now - self._window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) > self._max_signals

    def signal_count(self, session_id: str, *, now: float | None = None) -> int:
        now = now if now is not None else time.monotonic()
        window = self._signal_times[session_id]
        cutoff = now - self._window_seconds
        return len([t for t in window if t >= cutoff])

    def reset(self, session_id: str) -> None:
        self._signal_times.pop(session_id, None)


@dataclass
class HumanApprovalTimeoutPolicy:
    """Rule 5.3 -- pure decision logic for the three named timeout
    behaviors; the actual asyncio/wall-clock waiting happens in the
    LangGraph interrupt nodes (M10). Each method here just answers
    "given this elapsed time, what should happen?".
    """

    question_suggestion_timeout_seconds: float = 60.0
    phase_transition_alert_seconds: float = 300.0

    def question_suggestion_outcome(self, elapsed_seconds: float) -> str:
        """'On timeout (interviewer doesn't act within 60s): auto-
        dismisses suggestion, interviewer continues without AI
        suggestion — session is NOT blocked.'"""
        if elapsed_seconds >= self.question_suggestion_timeout_seconds:
            return "AUTO_DISMISSED"
        return "AWAITING_HUMAN"

    def scorecard_approval_outcome(self, elapsed_seconds: float) -> str:
        """'scorecard approval waits indefinitely (no auto-approval
        ever)' -- always AWAITING_HUMAN, regardless of elapsed time.
        Method exists (rather than being inlined by callers) so the
        "never auto-approve" invariant is enforced in exactly one place."""
        return "AWAITING_HUMAN"

    def phase_transition_outcome(self, elapsed_seconds: float) -> str:
        """'phase transitions: timeout after 5 min -> interviewer sees
        persistent alert' -- never auto-transitions."""
        if elapsed_seconds >= self.phase_transition_alert_seconds:
            return "PERSISTENT_ALERT_SHOWN"
        return "AWAITING_HUMAN"


class FallbackHandler:
    """Rule 5.1. Builds the `FallbackDecision` + logged
    `GuardrailCheckResult` for any of: a guardrail BLOCKED the input/
    output, an agent errored after N retries, output failed schema
    validation after N retries, or an LLM call timed out.
    """

    def build(
        self,
        *,
        agent_name: str,
        reason: str,
        tenant_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> FallbackDecision:
        event = GuardrailCheckResult(
            layer=LAYER,
            rule="5.1_agent_failure_graceful_degradation",
            agent_name=agent_name,
            action_taken="BLOCKED",
            trigger_reason=reason,
            tenant_id=tenant_id,
            session_id=session_id,
        )
        return FallbackDecision(
            triggered=True,
            reason=reason,
            interviewer_message="AI suggestions temporarily unavailable",
            surface_to_candidate=False,
            event=event,
        )

    def build_circuit_breaker_trip(
        self,
        *,
        agent_name: str,
        node_key: str,
        cooldown_seconds: float,
        tenant_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> FallbackDecision:
        reason = (
            f"circuit breaker tripped for node '{node_key}' "
            f"(too many triggers in the sliding window); disabled for {cooldown_seconds:.0f}s"
        )
        event = GuardrailCheckResult(
            layer=LAYER,
            rule="5.2_orchestrator_loop_prevention",
            agent_name=agent_name,
            action_taken="BLOCKED",
            trigger_reason=reason,
            tenant_id=tenant_id,
            session_id=session_id,
        )
        return FallbackDecision(
            triggered=True,
            reason=reason,
            interviewer_message="AI suggestions temporarily unavailable",
            surface_to_candidate=False,
            event=event,
        )