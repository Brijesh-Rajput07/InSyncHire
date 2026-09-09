# LOCATION: services/interview_service/tests/test_ws_gateway_integration.py

"""
Integration test for the M9 WebSocket gateway.

*** WHY A REAL SERVER, NOT STARLETTE'S TestClient ***
Every other integration test in this service (and every other service
in this repo) uses `httpx.ASGITransport` or Starlette's `TestClient`
against the app in-process. For plain HTTP request/response, that's
correct and fast. For WebSockets specifically it is NOT safe here:
Starlette's `TestClient.websocket_connect()` runs each connection's
ASGI app instance in its OWN dedicated background thread with its OWN
event loop (via `anyio`'s blocking-portal mechanism). That's fine for a
single connection, or for connections that never need to await
something bound to another connection's loop -- but this gateway's
whole job is cross-connection message routing (`broadcaster.publish`
sends to OTHER connections' `WebSocket` objects) AND per-message tenant
DB access (`code_update`, `end_session`). Doing both together across
two separately-portaled `TestClient` connections deadlocks: a coroutine
awaiting a SQLAlchemy async-engine operation whose underlying
`aiosqlite` connection primitives were first bound to a DIFFERENT
connection's event loop never resolves. This is a test-harness
limitation, not a bug in `ws_gateway.py` -- a real ASGI server
(Uvicorn) runs every connection on ONE shared event loop, exactly like
this service does in production, so cross-connection broadcast and
per-connection DB access both work correctly there. This test spins up
a real Uvicorn server on a local port in a background thread (Kafka
lifespan disabled via `lifespan="off"`, so no real broker is needed)
and drives it with the `websockets` client library over a real TCP
socket -- the same shape a real browser client would use.

Because the server thread's `TenantResolver` runs on a genuinely
different event loop than the test's own setup/assertion code, it is
given its OWN independently-constructed engines pointed at the SAME
file-based SQLite DSNs the test seeded (`conftest.create_temp_global_sqlite_dsn`
-- an in-memory DB is only visible to the one engine that created it,
which is why this test doesn't use `build_global_test_engine()` like
every other test in this suite).

Covers: invalid/expired token rejected at handshake, session_id
mismatch rejected, first staff join transitions SCHEDULED -> IN_PROGRESS,
chat relay (and observer's chat send rejected), code_update relay +
`code_snapshots` persistence, agent_event routed to interviewer only
(never candidate/observer), and end_session (staff-only) transitioning
to COMPLETED + publishing `interview.completed`.
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
from insynchire_events.topics import Topics
from interview_service.broadcaster import InProcessBroadcaster
from interview_service.connection_manager import SessionConnectionRegistry
from interview_service.dependencies import (
    get_publish,
    get_scheduling_service,
    get_tenant_resolver,
    get_ws_broadcaster,
    get_ws_connect_token_service,
    get_ws_registry,
)
from interview_service.main import app
from interview_service.repositories import CodeSnapshotRepository, InterviewSessionRepository
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
    def __init__(
        self, *, tenant, interview, ws_token_service, publisher, resolver_setup, port, server, thread,
        setup_engine, server_engine,
    ):
        self.tenant = tenant
        self.interview = interview
        self.ws_token_service = ws_token_service
        self.publisher = publisher
        self.resolver_setup = resolver_setup  # for test-side verification queries only
        self.port = port
        self.server = server
        self.thread = thread
        self.setup_engine = setup_engine
        self.server_engine = server_engine

    def issue_ws_token(self, *, user_id: uuid.UUID, role_in_session: str) -> str:
        return self.ws_token_service.issue(
            tenant_id=self.tenant.tenant_id, session_id=self.interview.session_id,
            user_id=user_id, role_in_session=role_in_session,
        )

    def ws_url(self, token: str) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/interviews/{self.interview.session_id}?token={token}"


async def _build_harness(*, interviewer_ids, observer_ids=None, candidate_id=None) -> _Harness:
    global_dsn = await create_temp_global_sqlite_dsn()
    crypto = build_test_crypto()
    room_crypto = build_test_room_token_crypto()
    ws_token_service = build_test_ws_token_service(room_crypto)

    # --- setup-side engine/resolver (this test's own event loop) ---
    setup_engine = make_engine(global_dsn)
    setup_session_factory = make_session_factory(setup_engine)
    tenant = await seed_active_tenant(setup_session_factory, crypto, subdomain="acme")
    resolver_setup = TenantResolver(global_session_factory=setup_session_factory, crypto=crypto)

    scheduling_service_setup = SchedulingService(publish=FakePublisher().publish, room_token_crypto=room_crypto)
    db_session, _ = await resolver_setup.get_session_for_tenant_id(tenant.tenant_id)
    interview = await scheduling_service_setup.schedule_interview(
        session=db_session, tenant_id=tenant.tenant_id, scheduled_by=uuid.uuid4(),
        job_id=uuid.uuid4(), application_id=uuid.uuid4(), candidate_user_id=candidate_id or uuid.uuid4(),
        interviewer_ids=interviewer_ids, observer_ids=observer_ids or [], scheduled_at=_future_time(), trace_id="t1",
    )

    # --- server-side engine/resolver -- a SEPARATE instance, only ever
    # touched from within the background server thread's own event loop.
    server_engine = make_engine(global_dsn)
    server_session_factory = make_session_factory(server_engine)
    resolver_server = TenantResolver(global_session_factory=server_session_factory, crypto=crypto)

    registry = SessionConnectionRegistry()
    broadcaster = InProcessBroadcaster(registry)
    ws_publisher = FakePublisher()

    app.dependency_overrides[get_tenant_resolver] = lambda: resolver_server
    app.dependency_overrides[get_scheduling_service] = lambda: SchedulingService(
        publish=ws_publisher.publish, room_token_crypto=room_crypto
    )
    app.dependency_overrides[get_ws_registry] = lambda: registry
    app.dependency_overrides[get_ws_broadcaster] = lambda: broadcaster
    app.dependency_overrides[get_ws_connect_token_service] = lambda: ws_token_service
    app.dependency_overrides[get_publish] = lambda: ws_publisher.publish

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

    return _Harness(
        tenant=tenant, interview=interview, ws_token_service=ws_token_service, publisher=ws_publisher,
        resolver_setup=resolver_setup, port=port, server=server, thread=thread,
        setup_engine=setup_engine, server_engine=server_engine,
    )


async def _teardown(harness: _Harness) -> None:
    app.dependency_overrides.clear()
    harness.server.should_exit = True
    await asyncio.to_thread(harness.thread.join, 5)
    await harness.resolver_setup.dispose_all()
    await harness.setup_engine.dispose()
    # `server_engine` (and the tenant-DB engine `resolver_server` cached
    # internally) were only ever actually used from WITHIN the server
    # thread's own event loop -- disposing them from this (the test's)
    # loop risks reintroducing the exact cross-loop hang this whole
    # module's docstring explains. Left for garbage collection; the
    # resulting "non-checked-in connection" warnings in test output are
    # cosmetic, not a test failure.


async def _refresh_session(harness: _Harness):
    db_session, _ = await harness.resolver_setup.get_session_for_tenant_id(harness.tenant.tenant_id)
    return await InterviewSessionRepository(db_session).get_by_id(harness.interview.session_id)


def test_handshake_rejects_invalid_token():
    async def _run():
        harness = await _build_harness(interviewer_ids=[uuid.uuid4()])
        try:
            import pytest as _pytest

            with _pytest.raises(websockets.exceptions.InvalidStatus):
                async with websockets.connect(
                    f"ws://127.0.0.1:{harness.port}/ws/interviews/{harness.interview.session_id}?token=garbage"
                ):
                    pass
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_handshake_rejects_session_id_mismatch():
    async def _run():
        harness = await _build_harness(interviewer_ids=[uuid.uuid4()])
        try:
            wrong_session_token = harness.ws_token_service.issue(
                tenant_id=harness.tenant.tenant_id, session_id=uuid.uuid4(),
                user_id=uuid.uuid4(), role_in_session="interviewer",
            )
            import pytest as _pytest

            with _pytest.raises(websockets.exceptions.InvalidStatus):
                async with websockets.connect(harness.ws_url(wrong_session_token)):
                    pass
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_first_staff_join_starts_session():
    async def _run():
        interviewer_id = uuid.uuid4()
        harness = await _build_harness(interviewer_ids=[interviewer_id])
        try:
            token = harness.issue_ws_token(user_id=interviewer_id, role_in_session="interviewer")
            async with websockets.connect(harness.ws_url(token)) as ws:
                first_message = json.loads(await ws.recv())
                assert first_message == {"type": "session_started"}

            refreshed = await _refresh_session(harness)
            assert refreshed.status == "IN_PROGRESS"
            assert refreshed.started_at is not None
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_candidate_joining_alone_does_not_start_session():
    async def _run():
        candidate_id = uuid.uuid4()
        harness = await _build_harness(interviewer_ids=[uuid.uuid4()], candidate_id=candidate_id)
        try:
            token = harness.issue_ws_token(user_id=candidate_id, role_in_session="candidate")
            async with websockets.connect(harness.ws_url(token)):
                pass  # nothing broadcast to a lone candidate connection

            refreshed = await _refresh_session(harness)
            assert refreshed.status == "SCHEDULED"
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_chat_relayed_between_participants():
    async def _run():
        interviewer_id, candidate_id = uuid.uuid4(), uuid.uuid4()
        harness = await _build_harness(interviewer_ids=[interviewer_id], candidate_id=candidate_id)
        try:
            interviewer_token = harness.issue_ws_token(user_id=interviewer_id, role_in_session="interviewer")
            candidate_token = harness.issue_ws_token(user_id=candidate_id, role_in_session="candidate")

            async with websockets.connect(harness.ws_url(interviewer_token)) as interviewer_ws:
                await interviewer_ws.recv()  # session_started

                async with websockets.connect(harness.ws_url(candidate_token)) as candidate_ws:
                    await interviewer_ws.recv()  # participant_joined (candidate)

                    await candidate_ws.send(json.dumps({"type": "chat", "body": "Hi, ready to start!"}))
                    received = json.loads(await interviewer_ws.recv())
                    assert received["type"] == "chat"
                    assert received["body"] == "Hi, ready to start!"
                    assert received["from_role"] == "candidate"
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_observer_cannot_send_chat():
    async def _run():
        interviewer_id, observer_id = uuid.uuid4(), uuid.uuid4()
        harness = await _build_harness(interviewer_ids=[interviewer_id], observer_ids=[observer_id])
        try:
            observer_token = harness.issue_ws_token(user_id=observer_id, role_in_session="observer")

            async with websockets.connect(harness.ws_url(observer_token)) as observer_ws:
                await observer_ws.recv()  # session_started (observer is staff too)

                await observer_ws.send(json.dumps({"type": "chat", "body": "trying to chat"}))
                received = json.loads(await observer_ws.recv())
                assert received["type"] == "error"
                assert "cannot send chat" in received["detail"].lower()
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_code_update_relayed_and_persisted():
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

                    await candidate_ws.send(
                        json.dumps({"type": "code_update", "content": "def solve(): pass", "language": "python"})
                    )
                    received = json.loads(await interviewer_ws.recv())
                    assert received["type"] == "code_update"
                    assert received["content"] == "def solve(): pass"
                    assert received["snapshot_index"] == 0

            db_session, _ = await harness.resolver_setup.get_session_for_tenant_id(harness.tenant.tenant_id)
            snapshots = await CodeSnapshotRepository(db_session).list_for_session(harness.interview.session_id)
            assert len(snapshots) == 1
            assert snapshots[0].content == "def solve(): pass"
            assert snapshots[0].snapshot_index == 0
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_agent_event_only_delivered_to_interviewer():
    async def _run():
        interviewer_id, observer_id, candidate_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        harness = await _build_harness(
            interviewer_ids=[interviewer_id], observer_ids=[observer_id], candidate_id=candidate_id
        )
        try:
            interviewer_token = harness.issue_ws_token(user_id=interviewer_id, role_in_session="interviewer")
            observer_token = harness.issue_ws_token(user_id=observer_id, role_in_session="observer")
            candidate_token = harness.issue_ws_token(user_id=candidate_id, role_in_session="candidate")

            async with websockets.connect(harness.ws_url(interviewer_token)) as interviewer_ws:
                await interviewer_ws.recv()  # session_started

                async with websockets.connect(harness.ws_url(observer_token)) as observer_ws:
                    await interviewer_ws.recv()  # participant_joined (observer)

                    async with websockets.connect(harness.ws_url(candidate_token)) as candidate_ws:
                        await interviewer_ws.recv()  # participant_joined (candidate)
                        await observer_ws.recv()  # participant_joined (candidate) -- observer also connected already

                        await interviewer_ws.send(json.dumps(
                            {"type": "agent_event", "event_type": "copilot_suggestion",
                             "payload": {"hint": "check edge cases"}}
                        ))
                        received = json.loads(await interviewer_ws.recv())
                        assert received["type"] == "agent_event"
                        assert received["event_type"] == "copilot_suggestion"

                        # Prove observer/candidate never got the agent_event
                        # by sending a harmless chat right after and
                        # confirming it (not a leaked agent_event) is what
                        # they each receive next.
                        await interviewer_ws.send(json.dumps({"type": "chat", "body": "isolation check"}))
                        observer_received = json.loads(await observer_ws.recv())
                        candidate_received = json.loads(await candidate_ws.recv())
                        assert observer_received["type"] == "chat"
                        assert candidate_received["type"] == "chat"
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_end_session_by_staff_completes_and_publishes_event():
    async def _run():
        recruiter_id = uuid.uuid4()
        harness = await _build_harness(interviewer_ids=[uuid.uuid4()])
        try:
            recruiter_token = harness.issue_ws_token(user_id=recruiter_id, role_in_session="recruiter")

            async with websockets.connect(harness.ws_url(recruiter_token)) as recruiter_ws:
                await recruiter_ws.recv()  # session_started

                await recruiter_ws.send(json.dumps({"type": "end_session"}))
                received = json.loads(await recruiter_ws.recv())
                assert received == {"type": "session_completed"}

            refreshed = await _refresh_session(harness)
            assert refreshed.status == "COMPLETED"
            assert refreshed.completed_at is not None

            topics = [t for t, _ in harness.publisher.published]
            assert Topics.INTERVIEW_COMPLETED.value in topics
        finally:
            await _teardown(harness)

    asyncio.run(_run())


def test_observer_cannot_end_session():
    async def _run():
        observer_id = uuid.uuid4()
        harness = await _build_harness(interviewer_ids=[uuid.uuid4()], observer_ids=[observer_id])
        try:
            observer_token = harness.issue_ws_token(user_id=observer_id, role_in_session="observer")

            async with websockets.connect(harness.ws_url(observer_token)) as observer_ws:
                await observer_ws.recv()  # session_started (observer is staff too)

                await observer_ws.send(json.dumps({"type": "end_session"}))
                received = json.loads(await observer_ws.recv())
                assert received["type"] == "error"
                assert "company_admin/recruiter" in received["detail"]

            refreshed = await _refresh_session(harness)
            # Observer is a STAFF role too, so its own connection already
            # transitioned SCHEDULED -> IN_PROGRESS on join -- being denied
            # end_session doesn't roll that back.
            assert refreshed.status == "IN_PROGRESS"
        finally:
            await _teardown(harness)

    asyncio.run(_run())