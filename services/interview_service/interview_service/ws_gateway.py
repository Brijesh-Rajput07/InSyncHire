# LOCATION: services/interview_service/interview_service/ws_gateway.py

"""
Live interview room WebSocket gateway (Section: STAGE 6 -- LIVE
INTERVIEW ROOM; Section 10e).

Handles the pieces of the live room that are pure message-routing +
persistence, NOT the pieces that need real third-party infrastructure
this milestone doesn't wire up yet:

  - **Chat** (Section: "c. Text chat (WebSocket, role-gated)"): relayed
    to every other connection on the session. `observer` is read-only
    (Section: "Observer: silent room access ... Cannot chat") -- a
    chat send from an observer connection is rejected with an
    `error` message back to the sender, never relayed.
  - **Collaborative code editor** (Section: "b. Collaborative code
    editor (Monaco + Yjs CRDT over WebSocket + Redis pub/sub)"): *** THIS
    IS AN INTERIM IMPLEMENTATION ***. A real Yjs CRDT integration
    (binary y-protocol awareness/sync messages, operational-transform
    merge semantics) is out of scope for this milestone -- what's
    implemented here is a simplified "whole-document" relay: a
    `code_update` message carries the editor's full current content,
    which is broadcast verbatim to every other connection AND persisted
    as the next `code_snapshots` row (Section: "code_snapshots: full
    history with diffs — enables playback"). This is NOT
    conflict-resolved the way real CRDT sync is -- two simultaneous
    edits from different participants will race, with last-write-wins
    semantics, rather than merging. Swapping in real Yjs sync (a
    `y-websocket`-compatible binary relay) is a follow-up milestone;
    this interim version is flagged the same way
    `job_service.public_board_service` and
    `agent_service.tools.rag_job_similarity_tool` flagged their own
    interim implementations, and satisfies the SPIRIT of the feature
    (participants see each other's edits live, full history is
    persisted) at the boundary a client actually touches.
  - **Agent event channel** (Section: "f. Interviewer Co-Pilot panel
    ... never emitted to candidate" / "g. Live integrity signals panel
    ... interviewer only"): the emission PLUMBING is built here (an
    `agent_event` message type, routed to `interviewer`-role
    connections only, via `Broadcaster.publish(..., only_roles={"interviewer"})`)
    so the LangGraph interview pipeline (Graph 1, M10) has a channel to
    publish into once it exists. No agent actually runs yet -- there is
    no LLM call anywhere in this module. `agent_event` messages
    received here are for testing/demo purposes only until M10 wires
    a real emitter in.
  - **Session state management**: the first STAFF connection (not a
    candidate alone) transitions `interview_sessions.status` from
    SCHEDULED to IN_PROGRESS and sets `started_at`; an explicit
    `end_session` message (staff-only) transitions to COMPLETED, sets
    `completed_at`, and publishes `interview.completed` to Kafka (the
    topic/schema already existed in `insynchire-events` before this
    milestone).

Redis pub/sub (Section: "WebSocket message broker across multiple
FastAPI instances") is NOT wired up -- see `broadcaster.py`'s module
docstring for the explicit, documented gap and the drop-in replacement
path.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from insynchire_events import Topics
from insynchire_events.schemas import InterviewCompletedEvent

from .broadcaster import InProcessBroadcaster
from .connection_manager import Connection, SessionConnectionRegistry
from .dependencies import (
    get_publish,
    get_tenant_resolver,
    get_ws_broadcaster,
    get_ws_connect_token_service,
    get_ws_registry,
)
from .repositories import CodeSnapshotRepository, InterviewSessionRepository
from .tenant_db import TenantResolver
from .ws_tokens import WSConnectTokenService, WSTokenError

logger = logging.getLogger("interview_service.ws_gateway")

router = APIRouter()

CANDIDATE_ROLE = "candidate"
OBSERVER_ROLE = "observer"
STAFF_ROLES = {"company_admin", "recruiter", "interviewer", "observer"}
SESSION_END_ALLOWED_ROLES = {"company_admin", "recruiter"}

WS_CLOSE_INVALID_TOKEN = 4401
WS_CLOSE_SESSION_MISMATCH = 4403


@router.websocket("/ws/interviews/{session_id}")
async def interview_ws(
    websocket: WebSocket,
    session_id: uuid.UUID,
    token: str = Query(...),
    token_service: WSConnectTokenService = Depends(get_ws_connect_token_service),
    registry: SessionConnectionRegistry = Depends(get_ws_registry),
    broadcaster: InProcessBroadcaster = Depends(get_ws_broadcaster),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
    publish=Depends(get_publish),
):
    try:
        claims = token_service.verify(token)
    except WSTokenError:
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return

    if claims.session_id != session_id:
        await websocket.close(code=WS_CLOSE_SESSION_MISMATCH)
        return

    await websocket.accept()

    connection = Connection(websocket=websocket, user_id=claims.user_id, role_in_session=claims.role_in_session)
    registry.add(session_id, connection)

    try:
        if claims.role_in_session in STAFF_ROLES:
            await _maybe_start_session(
                tenant_resolver=tenant_resolver, broadcaster=broadcaster,
                tenant_id=claims.tenant_id, session_id=session_id,
            )

        await broadcaster.publish(
            session_id,
            {"type": "participant_joined", "role_in_session": claims.role_in_session},
            exclude_connection=connection,
        )

        while True:
            message = await websocket.receive_json()
            await _handle_message(
                message,
                session_id=session_id,
                tenant_id=claims.tenant_id,
                user_id=claims.user_id,
                role_in_session=claims.role_in_session,
                connection=connection,
                broadcaster=broadcaster,
                tenant_resolver=tenant_resolver,
                publish=publish,
            )
    except WebSocketDisconnect:
        pass
    finally:
        registry.remove(session_id, connection)
        await broadcaster.publish(
            session_id, {"type": "participant_left", "role_in_session": claims.role_in_session}
        )


async def _maybe_start_session(
    *, tenant_resolver: TenantResolver, broadcaster: InProcessBroadcaster, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> None:
    """A candidate connecting alone should never start the interview
    clock; only a staff connection (interviewer/observer/recruiter/
    company_admin) does. Idempotent -- only fires the transition once
    (checks current status first)."""
    db_session, _ = await tenant_resolver.get_session_for_tenant_id(tenant_id)
    try:
        interview = await InterviewSessionRepository(db_session).get_by_id(session_id)
        if interview is not None and interview.status == "SCHEDULED":
            interview.status = "IN_PROGRESS"
            interview.started_at = datetime.now(timezone.utc)
            await db_session.commit()
            await broadcaster.publish(session_id, {"type": "session_started"})
    finally:
        await db_session.close()


async def _handle_message(
    message: dict[str, Any],
    *,
    session_id: uuid.UUID,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role_in_session: str,
    connection: Connection,
    broadcaster: InProcessBroadcaster,
    tenant_resolver: TenantResolver,
    publish,
) -> None:
    message_type = message.get("type")

    if message_type == "chat":
        await _handle_chat(
            message, session_id=session_id, role_in_session=role_in_session,
            connection=connection, broadcaster=broadcaster,
        )
    elif message_type == "code_update":
        await _handle_code_update(
            message, session_id=session_id, tenant_id=tenant_id, connection=connection,
            broadcaster=broadcaster, tenant_resolver=tenant_resolver,
        )
    elif message_type == "agent_event":
        await _handle_agent_event(message, session_id=session_id, broadcaster=broadcaster)
    elif message_type == "end_session":
        await _handle_end_session(
            session_id=session_id, tenant_id=tenant_id, role_in_session=role_in_session,
            connection=connection, broadcaster=broadcaster, tenant_resolver=tenant_resolver,
            publish=publish,
        )
    else:
        await connection.websocket.send_json({"type": "error", "detail": f"Unknown message type '{message_type}'"})


async def _handle_chat(
    message: dict[str, Any], *, session_id: uuid.UUID, role_in_session: str,
    connection: Connection, broadcaster: InProcessBroadcaster,
) -> None:
    if role_in_session == OBSERVER_ROLE:
        await connection.websocket.send_json(
            {"type": "error", "detail": "Observers cannot send chat messages"}
        )
        return

    await broadcaster.publish(
        session_id,
        {"type": "chat", "from_user_id": str(connection.user_id), "from_role": role_in_session,
         "body": message.get("body", "")},
        exclude_connection=connection,
    )


async def _handle_code_update(
    message: dict[str, Any], *, session_id: uuid.UUID, tenant_id: uuid.UUID, connection: Connection,
    broadcaster: InProcessBroadcaster, tenant_resolver: TenantResolver,
) -> None:
    content = message.get("content", "")
    language = message.get("language")

    db_session, _ = await tenant_resolver.get_session_for_tenant_id(tenant_id)
    try:
        repo = CodeSnapshotRepository(db_session)
        previous = await repo.get_latest(session_id)
        snapshot = await repo.create_next(
            tenant_id=tenant_id, session_id=session_id, content=content, language=language,
            diff_from_prev=None if previous is None else _naive_diff(previous.content, content),
        )
        await db_session.commit()
    finally:
        await db_session.close()

    await broadcaster.publish(
        session_id,
        {
            "type": "code_update", "content": content, "language": language,
            "snapshot_index": snapshot.snapshot_index, "from_user_id": str(connection.user_id),
        },
        exclude_connection=connection,
    )


def _naive_diff(before: str, after: str) -> str:
    """Deliberately minimal -- a real diff algorithm (difflib, or the
    real Yjs update encoding once that's wired in) is not needed for
    this milestone's playback-history purpose; storing the raw
    before/after lengths is enough to prove `diff_from_prev` is
    populated without pulling in a diff library for an interim
    implementation. Replace when real Yjs sync lands."""
    return f"len {len(before)} -> {len(after)}"


async def _handle_agent_event(
    message: dict[str, Any], *, session_id: uuid.UUID, broadcaster: InProcessBroadcaster
) -> None:
    """Section: Co-Pilot/Integrity events are emitted to the
    INTERVIEWER WebSocket only -- never candidate, never observer, and
    (per the plan's own wording, "interviewer WebSocket panel only")
    not even company_admin/recruiter. No agent actually produced this
    event yet (M10) -- this handler only proves the routing is correct."""
    await broadcaster.publish(
        session_id,
        {"type": "agent_event", "event_type": message.get("event_type"), "payload": message.get("payload")},
        only_roles={"interviewer"},
    )


def _as_aware_utc(dt: datetime) -> datetime:
    """Some DB drivers (notably SQLite, used in this repo's tests) don't
    round-trip timezone info even on a `DateTime(timezone=True)` column
    the way Postgres does -- they hand back a naive datetime. We always
    stored these as UTC, so a naive value is assumed to already be UTC.
    Same helper/rationale as `tenant_service.invite_acceptance_service`'s
    `_as_aware_utc`."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _handle_end_session(
    *, session_id: uuid.UUID, tenant_id: uuid.UUID, role_in_session: str, connection: Connection,
    broadcaster: InProcessBroadcaster, tenant_resolver: TenantResolver, publish,
) -> None:
    if role_in_session not in SESSION_END_ALLOWED_ROLES:
        await connection.websocket.send_json(
            {"type": "error", "detail": "Only company_admin/recruiter may end the session"}
        )
        return

    db_session, _ = await tenant_resolver.get_session_for_tenant_id(tenant_id)
    try:
        interview = await InterviewSessionRepository(db_session).get_by_id(session_id)
        if interview is None:
            await connection.websocket.send_json({"type": "error", "detail": "Session not found"})
            return

        completed_at = datetime.now(timezone.utc)
        started_at = _as_aware_utc(interview.started_at) if interview.started_at else completed_at
        interview.status = "COMPLETED"
        interview.completed_at = completed_at
        await db_session.commit()
    finally:
        await db_session.close()

    await publish(
        Topics.INTERVIEW_COMPLETED.value,
        InterviewCompletedEvent(
            trace_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            session_id=session_id,
            completed_at=completed_at,
            duration_seconds=max(int((completed_at - started_at).total_seconds()), 0),
        ),
    )

    await broadcaster.publish(session_id, {"type": "session_completed"})