# LOCATION: services/interview_service/tests/test_agent_bridge.py

"""
Tests for `AgentBridge` and `CodeUpdateDebouncer` (M10 Slice 2).

These are focused unit/integration tests of the bridge module in
isolation -- no FastAPI app, no WebSocket, no tenant DB. The full
real-Uvicorn-server multi-connection WebSocket test proving
`ws_gateway.py`'s new message handlers actually call into this bridge
correctly lives in `test_ws_gateway_agent_integration.py`, following
the exact pattern M9's own `test_ws_gateway_integration.py` established
(a real server is required -- Starlette's `TestClient.websocket_connect()`
isolates each connection on its own event loop, which deadlocks on this
gateway's cross-connection broadcast + per-message DB access).
"""

import asyncio
import uuid

from agent_service.tools import CandidateQuestion
from interview_service.agent_bridge import AgentBridge, CodeUpdateDebouncer, build_default_question_pool_provider


# ── CodeUpdateDebouncer ──────────────────────────────────────────────

def test_debouncer_always_triggers_on_first_update():
    debouncer = CodeUpdateDebouncer()
    assert debouncer.should_trigger(session_id="s1", current_code="a = 1") is True


def test_debouncer_suppresses_rapid_small_edits():
    debouncer = CodeUpdateDebouncer(min_interval_seconds=10.0, min_char_delta=50)
    now = 1000.0
    debouncer.record_trigger(session_id="s1", code="a = 1", now=now)
    # 1 second later, tiny edit -- neither condition met
    assert debouncer.should_trigger(session_id="s1", current_code="a = 12", now=now + 1) is False


def test_debouncer_triggers_after_interval_elapses():
    debouncer = CodeUpdateDebouncer(min_interval_seconds=10.0, min_char_delta=50)
    now = 1000.0
    debouncer.record_trigger(session_id="s1", code="a = 1", now=now)
    assert debouncer.should_trigger(session_id="s1", current_code="a = 12", now=now + 11) is True


def test_debouncer_triggers_on_large_char_delta_even_within_interval():
    debouncer = CodeUpdateDebouncer(min_interval_seconds=10.0, min_char_delta=5)
    now = 1000.0
    debouncer.record_trigger(session_id="s1", code="a = 1", now=now)
    big_edit = "a = 1\n" * 10  # well over 5 chars different
    assert debouncer.should_trigger(session_id="s1", current_code=big_edit, now=now + 1) is True


def test_debouncer_sessions_are_independent():
    debouncer = CodeUpdateDebouncer(min_interval_seconds=10.0, min_char_delta=50)
    now = 1000.0
    debouncer.record_trigger(session_id="s1", code="a = 1", now=now)
    assert debouncer.should_trigger(session_id="s2", current_code="totally different code", now=now + 1) is True


def test_debouncer_reset_clears_history():
    debouncer = CodeUpdateDebouncer(min_interval_seconds=10.0, min_char_delta=50)
    now = 1000.0
    debouncer.record_trigger(session_id="s1", code="a = 1", now=now)
    debouncer.reset("s1")
    assert debouncer.should_trigger(session_id="s1", current_code="a = 12", now=now + 1) is True


# ── AgentBridge ──────────────────────────────────────────────────────

def test_maybe_trigger_code_analysis_skipped_when_debounced():
    async def _run():
        bridge = AgentBridge()
        session_id = uuid.uuid4()
        # First call always triggers and records...
        r1 = await bridge.maybe_trigger_code_analysis(
            session_id=session_id, tenant_id=None, candidate_user_id=None, interviewer_ids=[],
            phase="CODING_ROUND", current_code="def f(): pass", current_language="python",
            current_question={"test_cases": []},
        )
        assert r1 is not None

        # ...an immediate tiny follow-up (same debouncer instance) is
        # suppressed and returns None rather than invoking the graph.
        r2 = await bridge.maybe_trigger_code_analysis(
            session_id=session_id, tenant_id=None, candidate_user_id=None, interviewer_ids=[],
            phase="CODING_ROUND", current_code="def f(): pas", current_language="python",
            current_question={"test_cases": []},
        )
        assert r2 is None

    asyncio.run(_run())


def test_maybe_trigger_code_analysis_runs_real_graph_and_returns_result():
    async def _run():
        bridge = AgentBridge()
        session_id = uuid.uuid4()
        result = await bridge.maybe_trigger_code_analysis(
            session_id=session_id, tenant_id=None, candidate_user_id=None, interviewer_ids=[],
            phase="CODING_ROUND", current_code="def add(a, b):\n    return a + b", current_language="python",
            current_question={"test_cases": []},
        )
        assert result is not None
        assert len(result.state["code_analysis_results"]) == 1
        # Placeholder LLM returns 50.0 -- never triggers Rule 2.2's
        # >80%-vs-zero-passed contradiction.
        assert result.state["code_analysis_results"][0]["correctness_pct"] == 50.0
        assert result.fallback_reason is None

    asyncio.run(_run())


def test_trigger_integrity_event_reaches_graph():
    async def _run():
        bridge = AgentBridge()
        session_id = uuid.uuid4()
        result = await bridge.trigger_integrity_event(
            session_id=session_id, tenant_id=None, candidate_user_id=None, interviewer_ids=[],
            phase="CODING_ROUND", event_type="paste_burst", confidence_score=0.9, raw_signal_data="burst",
        )
        assert len(result.state["integrity_signals"]) == 1
        assert result.state["integrity_signals"][0]["signal_type"] == "paste_burst"

    asyncio.run(_run())


def test_trigger_question_request_and_resume_approval():
    async def _run():
        pool = [CandidateQuestion(question_id="q1", title="Two Sum", body="b", difficulty="medium", topic_tags=["arrays"])]
        bridge = AgentBridge(question_pool_provider=build_default_question_pool_provider(pool))
        session_id = uuid.uuid4()

        r1 = await bridge.trigger_question_request(
            session_id=session_id, tenant_id=None, candidate_user_id=None, interviewer_ids=[], phase="CODING_ROUND",
        )
        assert r1.awaiting_human_approval is True
        assert r1.human_approval_type == "QUESTION"

        r2 = await bridge.resume_human_decision(session_id=session_id, decision="APPROVED")
        assert r2.state["human_approved_question"] is True
        assert r2.awaiting_human_approval is False

    asyncio.run(_run())


def test_trigger_phase_transition_and_resume_confirmed():
    async def _run():
        bridge = AgentBridge()
        session_id = uuid.uuid4()

        r1 = await bridge.trigger_phase_transition_request(
            session_id=session_id, tenant_id=None, candidate_user_id=None, interviewer_ids=[],
            phase="CODING_ROUND", next_phase="WRAP_UP",
        )
        assert r1.state["phase"] == "CODING_ROUND"  # not yet transitioned

        r2 = await bridge.resume_human_decision(session_id=session_id, decision="CONFIRMED")
        assert r2.state["phase"] == "WRAP_UP"

    asyncio.run(_run())


def test_get_state_reflects_accumulated_history():
    async def _run():
        bridge = AgentBridge()
        session_id = uuid.uuid4()
        assert await bridge.get_state(session_id) is None

        await bridge.maybe_trigger_code_analysis(
            session_id=session_id, tenant_id=None, candidate_user_id=None, interviewer_ids=[],
            phase="CODING_ROUND", current_code="pass", current_language="python",
            current_question={"test_cases": []},
        )
        snapshot = await bridge.get_state(session_id)
        assert snapshot is not None
        assert len(snapshot["code_analysis_results"]) == 1

    asyncio.run(_run())


def test_placeholder_report_synthesis_never_crashes_session_completed_trigger():
    """Even though full Report Synthesis wiring is M11's job, Graph 1's
    report_synthesis_node must not crash if SESSION_COMPLETED is
    triggered against this Slice-2 bridge -- proves the placeholder
    round-trips through the real schema validation cleanly."""

    async def _run():
        bridge = AgentBridge()
        session_id = uuid.uuid4()
        result = await bridge._interview_agent_service.handle_trigger(
            session_id=session_id, tenant_id=None, candidate_user_id=None, interviewer_ids=[],
            phase="WRAP_UP", trigger="SESSION_COMPLETED",
        )
        assert result.fallback_reason is None
        assert result.awaiting_human_approval is True
        assert result.human_approval_type == "SCORECARD"

    asyncio.run(_run())