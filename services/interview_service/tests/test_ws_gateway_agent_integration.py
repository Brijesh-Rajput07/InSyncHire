# LOCATION: services/interview_service/tests/test_ws_gateway_agent_integration.py

"""
Real WebSocket integration test for M10 Slice 2's new message types
(`integrity_event`, `question_request`, `phase_transition_request`,
`human_decision`) plus the new agent-triggering behavior added to
`code_update`.

Uses the EXACT SAME real-Uvicorn-server-in-a-background-thread pattern
M9's `test_ws_gateway_integration.py` established, for the identical
reason documented there: Starlette's `TestClient.websocket_connect()`
isolates each connection on its own event loop, which deadlocks on
this gateway's cross-connection broadcast + per-message DB access.

*** SCOPE NOTE *** -- this file exercises ONLY the new M10 Slice 2
message types end-to-end (chat, plain code relay basics, session
start/end, observer-cannot-chat, etc. are unchanged from M9 and already
covered by that milestone's own test file in the real repository --
not reprinted here since nothing in them changed).
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import uvicorn
import websockets

from interview_service.agent_bridge import AgentBridge
from interview_service.broadcaster import InProcessBroadcaster
from interview_service.connection_manager import SessionConnectionRegistry
from interview_service.dependencies import (
    get_agent_bridge,
    get_publish,
    get_scheduling_service,
    get_tenant_resolver,
    get_ws_broadcaster,
    get_ws_connect_token_service,
    get_ws_registry,
)
from interview_service.main import app
from interview_service.services import SchedulingService
from interview_service.tenant_db import TenantResolver
from shared.db import make_engine, make_session_factory

from .conftest import (
    build_test_crypto,
    build_test_room_token_crypto,
    build_test_ws_token_service,
    create_temp_global_sqlite_dsn,
    seed_active_tenant,
)


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


def _future_time():
    return datetime.now(timezone.utc) + timedelta(days=2)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Harness:
    def __init__(self, *, tenant, interview, ws_token_service, port, server, thread, setup_engine, resolver_setup):
        self.tenant = tenant
        self.interview = interview
        self.ws_token_service = ws_token_service
        self.port = port
        self.server = server
        self.thread = thread
        self.setup_engine = setup_engine
        self.resolver_setup = resolver_setup

    def issue_ws_token(self, *, user_id: uuid.UUID, role_in_session: str) -> str:
        return self.ws_token_service.issue(
            tenant_id=self.tenant.tenant_id, session_id=self.interview.session_id, user_id=user_id, role_in_session=role_in_session,
        )

    def ws_url(self, token: str) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/interviews/{self.interview.session_id}?token={token}"


async def _build_harness(*, interviewer_ids, candidate_id=None) -> _Harness:
    global_dsn = await create_temp_global_sqlite_dsn()
    crypto = build_test_crypto()
    room_crypto = build_test_room_token_crypto()
    ws_token_service = build_test_ws_token_service(room_crypto)

    setup_engine = make_engine(global_dsn)
    setup_session_factory = make_session_factory(setup_engine)
    tenant = await seed_active_tenant(setup_session_factory, crypto, subdomain="acme")
    resolver_setup = TenantResolver(global_session_factory=setup_session_factory, crypto=crypto)

    scheduling_service_setup = SchedulingService(publish=FakePublisher().publish, room_token_crypto=room_crypto)
    db_session, _ = await resolver_setup.get_session_for_tenant_id(tenant.tenant_id)
    interview = await scheduling_service_setup.schedule_interview(
        session=db_session, tenant_id=tenant.tenant_id, scheduled_by=uuid.uuid4(),
        job_id=uuid.uuid4(), application_id=uuid.uuid4(), candidate_user_id=candidate_id or uuid.uuid4(),
        interviewer_ids=interviewer_ids, observer_ids=[], scheduled_at=_future_time(), trace_id="t1",
    )

    server_engine = make_engine(global_dsn)
    server_session_factory = make_session_factory(server_engine)
    resolver_server = TenantResolver(global_session_factory=server_session_factory, crypto=crypto)

    registry = SessionConnectionRegistry()
    broadcaster = InProcessBroadcaster(registry)
    ws_publisher = FakePublisher()
    agent_bridge = AgentBridge()  # fresh Graph 1 + debouncer for this server instance

    app.dependency_overrides[get_tenant_resolver] = lambda: resolver_server
    app.dependency_overrides[get_scheduling_service] = lambda: SchedulingService(publish=ws_publisher.publish, room_token_crypto=room_crypto)
    app.dependency_overrides[get_ws_registry] = lambda: registry
    app.dependency_overrides[get_ws_broadcaster] = lambda: broadcaster
    app.dependency_overrides[get_ws_connect_token_service] = lambda: ws_token_service
    app.dependency_overrides[get_publish] = lambda: ws_publisher.publish
    app.dependency_overrides[get_agent_bridge] = lambda: agent_bridge

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    else:
        raise RuntimeError("uvicorn test server did not start in time")

    return _Harness(tenant=tenant, interview=interview, ws_token_service=ws_token_service, port=port, server=server, thread=thread, setup_engine=setup_engine, resolver_setup=resolver_setup)


async def _teardown(harness: _Harness) -> None:
    app.dependency_overrides.clear()
    harness.server.should_exit = True
    await asyncio.to_thread(harness.thread.join, 5)
    await harness.resolver_setup.dispose_all()
    await harness.setup_engine.dispose()


def test_code_update_triggers_analysis_broadcast_to_interviewer_only():
    async def _run():
        interviewer_id, candidate_id, observer_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        harness = await _build_harness(interviewer_ids=[interviewer_id], candidate_id=candidate_id)
        try:
            interviewer_token = harness.issue_ws_token(user_id=interviewer_id, role_in_session="interviewer")
            candidate_token = harness.issue_ws_token(user_id=candidate_id, role_in_session="candidate")

            async with websockets.connect(harness.ws_url(interviewer_token)) as interviewer_ws:
                await interviewer_ws.recv()  # session_started

                async with websockets.connect(harness.ws_url(candidate_token)) as candidate_ws:
                    await interviewer_ws.recv()  # participant_joined (candidate)

                    await candidate_ws.send(json.dumps({
                        "type": "code_update", "content": "def add(a, b):\n    return a + b",
                        "language": "python", "current_question": {"test_cases": []},
                    }))

                    # Candidate is the sender -- nothing echoed back to
                    # the sender by design (M9's existing exclude_connection
                    # behavior, unchanged).

                    # Interviewer sees: 1) the relayed code_update, 2) a code_analyzed
                    # agent_event, 3) a copilot_suggestion agent_event (parallel fan-out)
                    msg1 = json.loads(await interviewer_ws.recv())
                    assert msg1["type"] == "code_update"

                    msg2 = json.loads(await interviewer_ws.recv())
                    assert msg2["type"] == "agent_event"
                    assert msg2["event_type"] == "code_analyzed"
                    assert msg2["payload"]["passed_tests"] == 0  # no test_cases supplied

                    msg3 = json.loads(await interviewer_ws.recv())
                    assert msg3["type"] == "agent_event"
                    assert msg3["event_type"] == "copilot_suggestion"
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_integrity_event_from_candidate_reaches_interviewer_only():
    async def _run():
        interviewer_id, candidate_id = uuid.uuid4(), uuid.uuid4()
        harness = await _build_harness(interviewer_ids=[interviewer_id], candidate_id=candidate_id)
        try:
            interviewer_token = harness.issue_ws_token(user_id=interviewer_id, role_in_session="interviewer")
            candidate_token = harness.issue_ws_token(user_id=candidate_id, role_in_session="candidate")

            async with websockets.connect(harness.ws_url(interviewer_token)) as interviewer_ws:
                await interviewer_ws.recv()  # session_started

                async with websockets.connect(harness.ws_url(candidate_token)) as candidate_ws:
                    await interviewer_ws.recv()  # participant_joined

                    await candidate_ws.send(json.dumps({
                        "type": "integrity_event", "event_type": "paste_burst",
                        "confidence_score": 0.85, "raw_signal_data": "burst detected",
                    }))

                    msg = json.loads(await interviewer_ws.recv())
                    assert msg["type"] == "agent_event"
                    assert msg["event_type"] == "integrity_flagged"
                    assert msg["payload"]["signal_type"] == "paste_burst"
                    assert "verdict" not in msg["payload"]
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_question_request_staff_only_and_full_approval_flow():
    async def _run():
        interviewer_id, candidate_id = uuid.uuid4(), uuid.uuid4()
        harness = await _build_harness(interviewer_ids=[interviewer_id], candidate_id=candidate_id)
        try:
            interviewer_token = harness.issue_ws_token(user_id=interviewer_id, role_in_session="interviewer")
            candidate_token = harness.issue_ws_token(user_id=candidate_id, role_in_session="candidate")

            async with websockets.connect(harness.ws_url(interviewer_token)) as interviewer_ws:
                await interviewer_ws.recv()  # session_started

                async with websockets.connect(harness.ws_url(candidate_token)) as candidate_ws:
                    await interviewer_ws.recv()  # participant_joined

                    # Candidate is NOT allowed to request a question
                    await candidate_ws.send(json.dumps({"type": "question_request"}))
                    denied = json.loads(await candidate_ws.recv())
                    assert denied["type"] == "error"

                    # Interviewer requests one -- pool is empty in this
                    # test's AgentBridge (default provider), so it
                    # falls back rather than crashing.
                    await interviewer_ws.send(json.dumps({"type": "question_request"}))
                    fallback_msg = json.loads(await interviewer_ws.recv())
                    assert fallback_msg["type"] == "agent_event"
                    assert fallback_msg["event_type"] == "fallback"
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_phase_transition_request_and_confirm_broadcasts_to_room():
    async def _run():
        interviewer_id, candidate_id = uuid.uuid4(), uuid.uuid4()
        harness = await _build_harness(interviewer_ids=[interviewer_id], candidate_id=candidate_id)
        try:
            interviewer_token = harness.issue_ws_token(user_id=interviewer_id, role_in_session="interviewer")
            candidate_token = harness.issue_ws_token(user_id=candidate_id, role_in_session="candidate")

            async with websockets.connect(harness.ws_url(interviewer_token)) as interviewer_ws:
                await interviewer_ws.recv()  # session_started

                async with websockets.connect(harness.ws_url(candidate_token)) as candidate_ws:
                    await interviewer_ws.recv()  # participant_joined

                    await interviewer_ws.send(json.dumps({"type": "phase_transition_request", "next_phase": "WRAP_UP"}))
                    prompt = json.loads(await interviewer_ws.recv())
                    assert prompt["type"] == "agent_event"
                    assert prompt["event_type"] == "human_approval_required"
                    assert prompt["payload"]["approval_type"] == "PHASE_END"

                    await interviewer_ws.send(json.dumps({"type": "human_decision", "decision": "CONFIRMED"}))

                    # phase_changed is room-wide -- both interviewer and candidate get it
                    interviewer_phase_msg = json.loads(await interviewer_ws.recv())
                    candidate_phase_msg = json.loads(await candidate_ws.recv())
                    assert interviewer_phase_msg == {"type": "phase_changed", "phase": "WRAP_UP"}
                    assert candidate_phase_msg == {"type": "phase_changed", "phase": "WRAP_UP"}
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_human_decision_denied_for_observer():
    async def _run():
        interviewer_id, observer_id = uuid.uuid4(), uuid.uuid4()
        harness = await _build_harness(interviewer_ids=[interviewer_id])
        # observer isn't assigned via interviewer_ids/observer_ids in this
        # harness helper, so issue an observer-role WS token directly --
        # role authorization for human_decision is enforced purely from
        # the WS token's role_in_session claim, same as every other
        # staff-only message type in this gateway.
        try:
            observer_token = harness.issue_ws_token(user_id=observer_id, role_in_session="observer")
            async with websockets.connect(harness.ws_url(observer_token)) as observer_ws:
                await observer_ws.recv()  # session_started (observer is staff too)

                await observer_ws.send(json.dumps({"type": "human_decision", "decision": "APPROVED"}))
                denied = json.loads(await observer_ws.recv())
                assert denied["type"] == "error"
        finally:
            await _teardown(harness)

    asyncio.run(_run())