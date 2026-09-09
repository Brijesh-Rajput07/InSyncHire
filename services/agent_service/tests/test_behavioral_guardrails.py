# LOCATION: services/agent_service/tests/test_behavioral_guardrails.py

import uuid

from agent_service.guardrails.behavioral_guardrails import (
    CircuitBreaker,
    FallbackHandler,
    HumanApprovalTimeoutPolicy,
    IntegrityEscalationTracker,
)


def test_circuit_breaker_does_not_trip_under_threshold():
    breaker = CircuitBreaker(max_triggers=5, window_seconds=60, cooldown_seconds=300)
    now = 1000.0
    for i in range(5):
        tripped = breaker.record_trigger("node-a", now=now + i)
        assert tripped is False
    assert breaker.is_tripped("node-a", now=now + 5) is False


def test_circuit_breaker_trips_after_exceeding_max_triggers_in_window():
    """Rule 5.2: '>5 times in 60 seconds ... CIRCUIT BREAKER trips'."""
    breaker = CircuitBreaker(max_triggers=5, window_seconds=60, cooldown_seconds=300)
    now = 1000.0
    tripped_flags = [breaker.record_trigger("node-a", now=now + i) for i in range(6)]
    assert tripped_flags == [False, False, False, False, False, True]
    assert breaker.is_tripped("node-a", now=now + 6) is True


def test_circuit_breaker_disabled_for_cooldown_then_resets():
    breaker = CircuitBreaker(max_triggers=2, window_seconds=60, cooldown_seconds=300)
    now = 0.0
    breaker.record_trigger("node-a", now=now)
    breaker.record_trigger("node-a", now=now + 1)
    breaker.record_trigger("node-a", now=now + 2)  # 3rd trigger trips it
    assert breaker.is_tripped("node-a", now=now + 3) is True
    assert breaker.is_tripped("node-a", now=now + 301) is True  # trip happened at now+2, cools down at now+302
    assert breaker.is_tripped("node-a", now=now + 303) is False  # cooldown elapsed


def test_circuit_breaker_sliding_window_forgets_old_triggers():
    breaker = CircuitBreaker(max_triggers=2, window_seconds=10, cooldown_seconds=300)
    now = 0.0
    breaker.record_trigger("node-a", now=now)
    breaker.record_trigger("node-a", now=now + 1)
    # Triggers now fall outside the 10s window -- should NOT trip
    tripped = breaker.record_trigger("node-a", now=now + 50)
    assert tripped is False


def test_circuit_breaker_nodes_are_independent():
    breaker = CircuitBreaker(max_triggers=1, window_seconds=60, cooldown_seconds=300)
    breaker.record_trigger("node-a", now=0)
    tripped_a = breaker.record_trigger("node-a", now=1)
    tripped_b = breaker.record_trigger("node-b", now=1)
    assert tripped_a is True
    assert tripped_b is False


def test_circuit_breaker_reset_clears_history():
    breaker = CircuitBreaker(max_triggers=1, window_seconds=60, cooldown_seconds=300)
    breaker.record_trigger("node-a", now=0)
    breaker.reset("node-a")
    tripped = breaker.record_trigger("node-a", now=1)
    assert tripped is False


def test_integrity_escalation_tracker_escalates_after_threshold():
    """Rule 5.4: '>5 signals within 30 minutes -> escalate'."""
    tracker = IntegrityEscalationTracker(max_signals=5, window_seconds=1800)
    now = 0.0
    results = [tracker.record_signal("session-1", now=now + i) for i in range(6)]
    assert results == [False, False, False, False, False, True]


def test_integrity_escalation_tracker_sliding_window():
    tracker = IntegrityEscalationTracker(max_signals=2, window_seconds=10)
    now = 0.0
    tracker.record_signal("session-1", now=now)
    tracker.record_signal("session-1", now=now + 1)
    should_escalate = tracker.record_signal("session-1", now=now + 50)  # outside window
    assert should_escalate is False


def test_integrity_escalation_sessions_independent():
    tracker = IntegrityEscalationTracker(max_signals=1, window_seconds=1800)
    tracker.record_signal("session-1", now=0)
    escalate_1 = tracker.record_signal("session-1", now=1)
    escalate_2 = tracker.record_signal("session-2", now=1)
    assert escalate_1 is True
    assert escalate_2 is False


def test_human_approval_timeout_question_suggestion_auto_dismisses_after_60s():
    policy = HumanApprovalTimeoutPolicy()
    assert policy.question_suggestion_outcome(59.9) == "AWAITING_HUMAN"
    assert policy.question_suggestion_outcome(60.0) == "AUTO_DISMISSED"


def test_human_approval_timeout_scorecard_never_auto_approves():
    policy = HumanApprovalTimeoutPolicy()
    assert policy.scorecard_approval_outcome(0) == "AWAITING_HUMAN"
    assert policy.scorecard_approval_outcome(10**9) == "AWAITING_HUMAN"  # even after "forever"


def test_human_approval_timeout_phase_transition_persistent_alert_after_5min():
    policy = HumanApprovalTimeoutPolicy()
    assert policy.phase_transition_outcome(299.9) == "AWAITING_HUMAN"
    assert policy.phase_transition_outcome(300.0) == "PERSISTENT_ALERT_SHOWN"


def test_fallback_handler_builds_decision_never_surfaces_to_candidate():
    handler = FallbackHandler()
    decision = handler.build(agent_name="code_analysis", reason="LLM timeout after 3 retries")
    assert decision.triggered is True
    assert decision.surface_to_candidate is False
    assert decision.interviewer_message == "AI suggestions temporarily unavailable"
    assert decision.event is not None
    assert decision.event.action_taken == "BLOCKED"
    assert decision.event.rule == "5.1_agent_failure_graceful_degradation"


def test_fallback_handler_circuit_breaker_trip_decision():
    handler = FallbackHandler()
    decision = handler.build_circuit_breaker_trip(
        agent_name="integrity", node_key="tenant:session:integrity_node", cooldown_seconds=300
    )
    assert decision.triggered is True
    assert decision.surface_to_candidate is False
    assert decision.event.rule == "5.2_orchestrator_loop_prevention"