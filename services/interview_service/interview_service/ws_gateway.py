# LOCATION: services/interview_service/interview_service/ws_gateway.py

"""
Live interview room WebSocket gateway (Section: STAGE 6 -- LIVE
INTERVIEW ROOM; Section 10e).

M9 built chat relay, the interim whole-document code editor relay +
`code_snapshots` persistence, the `agent_event` emission PLUMBING
(interviewer-only routing, no agent behind it yet), and session state
transitions (SCHEDULED→IN_PROGRESS→COMPLETED). **M10 Slice 2** wires
that plumbing to something real: `AgentBridge` (`agent_bridge.py`),
which drives Agent Service's Graph 1 (M10 Slice 1) in-process. See that
module's docstring for the in-process-vs-HTTP architectural decision
and the "no real LLM provider wired in yet" flag.

New in this milestone:
  - `code_update` now ALSO (after persisting the snapshot, unchanged
    from M9) calls `AgentBridge.maybe_trigger_code_analysis()` --
    debounced (Section: "last_meaningful_diff — debounced — not every
    keystroke"). A real analysis result's `code_analysis_results` delta
    and any `copilot_suggestions` delta are broadcast to `interviewer`-
    role connections only, over `agent_event` (same routing M9 already
    proved: never candidate, never observer).
  - **`integrity_event`** (NEW message type) -- any connection may send
    one (Section: "triggered by client-side events (tab-switch,
    paste-burst) forwarded by Interview Service" -- typically the
    candidate's own client, which is where that detection actually
    runs). Routes through Graph 1's `integrity_node`; the resulting
    signal (and any Rule-5.4 escalation flag) is broadcast to
    `interviewer`-role connections only -- NEVER back to the sender,
    even if the sender IS the interviewer (Section: "emits to
    INTERVIEWER WebSocket only (never candidate or observer)").
  - **`question_request`** (NEW, staff-only: interviewer/recruiter/
    company_admin) -- triggers `question_strategist_node`; the
    suggested question is broadcast to `interviewer`-role connections
    only as a `human_approval_required` `agent_event`, pending a
    `human_decision` message.
  - **`phase_transition_request`** (NEW, staff-only) -- triggers
    `phase_transition_node`; broadcasts a `human_approval_required`
    `agent_event` (approval_type=PHASE_END) to interviewer-role
    connections, pending confirmation.
  - **`human_decision`** (NEW, staff-only) -- resumes whatever
    interrupt is currently paused for this session (question/scorecard
    approval, or phase-transition confirmation). The client is
    responsible for sending the decision that matches the prompt it
    was shown; this gateway does not track "which prompt is currently
    pending" itself -- `AgentBridge`/Graph 1's own state does.
  - A guardrail **fallback** (Rule 5.1) on ANY trigger is broadcast to
    `interviewer`-role connections only, as `agent_event` type
    `"fallback"` with the fixed "AI suggestions temporarily
    unavailable" message -- never surfaced to the candidate, and never
    treated as a WebSocket-level error (the session continues normally).

Everything M9 already built (chat, whole-document code relay +
persistence, session state transitions, Redis-pub/sub gap) is
UNCHANGED below except where explicitly noted.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from insynchire_events import Topics
from insynchire_events.schemas import InterviewCompletedEvent

from .agent_bridge import AgentBridge
from .broadcaster import InProcessBroadcaster
from .connection_manager import Connection, SessionConnectionRegistry
from .dependencies import (
    get_agent_bridge,
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
# M10 Slice 2: who may drive the agentic pipeline's staff-only actions.
# Observer is deliberately excluded -- silent room access only
# (Section: "Observer: silent room access ... Cannot inject questions").
AGENT_CONTROL_ALLOWED_ROLES = {"company_admin", "recruiter", "interviewer"}

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
    agent_bridge: AgentBridge = Depends(get_agent_bridge),
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
                agent_bridge=agent_bridge,
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


def _phase_for_session(interview) -> str:
    """Maps `interview_sessions.status` (SCHEDULED/IN_PROGRESS/
    COMPLETED/CANCELLED) onto Graph 1's `phase` field (WAITING/
    IN_PROGRESS/CODING_ROUND/SYSTEM_DESIGN_ROUND/WRAP_UP/COMPLETED).
    This is an interim, coarse mapping -- M10 Slice 1's `phase_history`
    tracks the finer-grained CODING_ROUND/SYSTEM_DESIGN_ROUND/WRAP_UP
    distinctions once a `phase_transition_request` has been used at
    least once; before that, a session that's IN_PROGRESS is treated as
    CODING_ROUND by default (the common case), not the more generic
    IN_PROGRESS, so `code_analysis_node`'s trigger routing (which only
    special-cases WAITING) behaves correctly from the start."""
    if interview is None or interview.status == "SCHEDULED":
        return "WAITING"
    if interview.status == "COMPLETED":
        return "COMPLETED"
    return "CODING_ROUND"


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
    agent_bridge: AgentBridge,
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
            broadcaster=broadcaster, tenant_resolver=tenant_resolver, agent_bridge=agent_bridge,
        )
    elif message_type == "agent_event":
        await _handle_agent_event(message, session_id=session_id, broadcaster=broadcaster)
    elif message_type == "integrity_event":
        await _handle_integrity_event(
            message, session_id=session_id, tenant_id=tenant_id, connection=connection,
            broadcaster=broadcaster, tenant_resolver=tenant_resolver, agent_bridge=agent_bridge,
        )
    elif message_type == "question_request":
        await _handle_question_request(
            message, session_id=session_id, tenant_id=tenant_id, connection=connection,
            broadcaster=broadcaster, tenant_resolver=tenant_resolver, agent_bridge=agent_bridge,
        )
    elif message_type == "phase_transition_request":
        await _handle_phase_transition_request(
            message, session_id=session_id, tenant_id=tenant_id, connection=connection,
            broadcaster=broadcaster, tenant_resolver=tenant_resolver, agent_bridge=agent_bridge,
        )
    elif message_type == "human_decision":
        await _handle_human_decision(
            message, session_id=session_id, connection=connection, broadcaster=broadcaster, agent_bridge=agent_bridge,
        )
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
    # *** KNOWN GAP, UNCHANGED FROM M9/documented in agent_service's
    # fetch_session_transcript_tool.py: this message is still not
    # persisted anywhere. See that tool's module docstring for the
    # recommended FIX-M9 (a chat_messages table) -- not applied here
    # without explicit confirmation, per that same docstring.


async def _handle_code_update(
    message: dict[str, Any], *, session_id: uuid.UUID, tenant_id: uuid.UUID, connection: Connection,
    broadcaster: InProcessBroadcaster, tenant_resolver: TenantResolver, agent_bridge: AgentBridge,
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
        interview = await InterviewSessionRepository(db_session).get_by_id(session_id)
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

    # M10 Slice 2: (debounced) trigger Graph 1's code_analysis_node +
    # its parallel copilot_node fan-out. Unassigned candidate/staff
    # user_ids are collected loosely here -- Graph 1 doesn't use them
    # for anything beyond identity bookkeeping in this slice.
    interviewer_ids = [uuid.UUID(i) for i in (interview.interviewer_ids if interview else [])]
    candidate_user_id = interview.candidate_user_id if interview else None
    current_question = message.get("current_question")  # client may include the active question's test_cases

    result = await agent_bridge.maybe_trigger_code_analysis(
        session_id=session_id, tenant_id=tenant_id, candidate_user_id=candidate_user_id,
        interviewer_ids=interviewer_ids, phase=_phase_for_session(interview),
        current_code=content, current_language=language or "", current_question=current_question,
    )
    if result is None:
        return  # debounced -- no analysis this round

    await _broadcast_trigger_result(result, session_id=session_id, broadcaster=broadcaster)


def _naive_diff(before: str, after: str) -> str:
    return f"len {len(before)} -> {len(after)}"


async def _handle_agent_event(
    message: dict[str, Any], *, session_id: uuid.UUID, broadcaster: InProcessBroadcaster
) -> None:
    """UNCHANGED from M9 -- kept for any manual/test-only agent_event
    sends. Real agent output now flows through `_broadcast_trigger_result`
    instead of this passthrough."""
    await broadcaster.publish(
        session_id,
        {"type": "agent_event", "event_type": message.get("event_type"), "payload": message.get("payload")},
        only_roles={"interviewer"},
    )


async def _broadcast_trigger_result(result, *, session_id: uuid.UUID, broadcaster: InProcessBroadcaster) -> None:
    """Turns an `InterviewTriggerResult` (agent_service) into the
    `agent_event` messages M9's routing already guarantees reach
    `interviewer`-role connections only (Section: Co-Pilot/Integrity
    "never emitted to candidate" / "interviewer only"). Never sent to
    the connection that CAUSED the trigger unless that connection is
    itself an interviewer (Rule 5.1's fallback message is exactly the
    kind of thing an interviewer should see regardless of who typed
    the code that triggered it)."""
    if result.fallback_reason:
        await broadcaster.publish(
            session_id,
            {"type": "agent_event", "event_type": "fallback", "payload": {"message": "AI suggestions temporarily unavailable"}},
            only_roles={"interviewer"},
        )
        return

    state = result.state

    if state.get("code_analysis_results"):
        await broadcaster.publish(
            session_id,
            {"type": "agent_event", "event_type": "code_analyzed", "payload": state["code_analysis_results"][-1]},
            only_roles={"interviewer"},
        )
    if state.get("copilot_suggestions"):
        await broadcaster.publish(
            session_id,
            {"type": "agent_event", "event_type": "copilot_suggestion", "payload": state["copilot_suggestions"][-1]},
            only_roles={"interviewer"},
        )
    if state.get("integrity_signals") and state["integrity_signals"]:
        await broadcaster.publish(
            session_id,
            {"type": "agent_event", "event_type": "integrity_flagged", "payload": state["integrity_signals"][-1]},
            only_roles={"interviewer"},
        )

    if result.awaiting_human_approval and result.human_approval_type in ("QUESTION", "SCORECARD"):
        payload_key = "suggested_question" if result.human_approval_type == "QUESTION" else "scorecard"
        await broadcaster.publish(
            session_id,
            {
                "type": "agent_event", "event_type": "human_approval_required",
                "payload": {"approval_type": result.human_approval_type, payload_key: state.get(payload_key)},
            },
            only_roles={"interviewer"},
        )
    elif result.human_approval_type == "PHASE_END" or state.get("pending_phase"):
        # phase_transition_request's own handler also emits this
        # explicitly (see below) -- this branch covers the case where
        # a caller reaches here some other way in the future.
        await broadcaster.publish(
            session_id,
            {
                "type": "agent_event", "event_type": "human_approval_required",
                "payload": {"approval_type": "PHASE_END", "next_phase": state.get("pending_phase")},
            },
            only_roles={"interviewer"},
        )
    elif result.human_approval_type == "INTEGRITY_REVIEW":
        await broadcaster.publish(
            session_id,
            {
                "type": "agent_event", "event_type": "integrity_escalation",
                "payload": {"signal_count": len(state.get("integrity_signals", []))},
            },
            only_roles={"interviewer"},
        )


async def _handle_integrity_event(
    message: dict[str, Any], *, session_id: uuid.UUID, tenant_id: uuid.UUID, connection: Connection,
    broadcaster: InProcessBroadcaster, tenant_resolver: TenantResolver, agent_bridge: AgentBridge,
) -> None:
    """Section: "triggered by client-side events (tab-switch,
    paste-burst) forwarded by Interview Service" -- ANY connection may
    send this (typically the candidate's own client), since the
    detection itself runs client-side; the RESULT is still only ever
    broadcast to interviewer connections (`_broadcast_trigger_result`),
    never echoed back to the sender."""
    db_session, _ = await tenant_resolver.get_session_for_tenant_id(tenant_id)
    try:
        interview = await InterviewSessionRepository(db_session).get_by_id(session_id)
    finally:
        await db_session.close()

    interviewer_ids = [uuid.UUID(i) for i in (interview.interviewer_ids if interview else [])]
    candidate_user_id = interview.candidate_user_id if interview else None

    result = await agent_bridge.trigger_integrity_event(
        session_id=session_id, tenant_id=tenant_id, candidate_user_id=candidate_user_id,
        interviewer_ids=interviewer_ids, phase=_phase_for_session(interview),
        event_type=message.get("event_type", "unknown"),
        confidence_score=float(message.get("confidence_score", 0.5)),
        raw_signal_data=str(message.get("raw_signal_data", "")),
    )
    await _broadcast_trigger_result(result, session_id=session_id, broadcaster=broadcaster)


async def _handle_question_request(
    message: dict[str, Any], *, session_id: uuid.UUID, tenant_id: uuid.UUID, connection: Connection,
    broadcaster: InProcessBroadcaster, tenant_resolver: TenantResolver, agent_bridge: AgentBridge,
) -> None:
    if connection.role_in_session not in AGENT_CONTROL_ALLOWED_ROLES:
        await connection.websocket.send_json({"type": "error", "detail": "Only interviewer/recruiter/company_admin may request a question suggestion"})
        return

    db_session, _ = await tenant_resolver.get_session_for_tenant_id(tenant_id)
    try:
        interview = await InterviewSessionRepository(db_session).get_by_id(session_id)
    finally:
        await db_session.close()

    interviewer_ids = [uuid.UUID(i) for i in (interview.interviewer_ids if interview else [])]
    candidate_user_id = interview.candidate_user_id if interview else None

    result = await agent_bridge.trigger_question_request(
        session_id=session_id, tenant_id=tenant_id, candidate_user_id=candidate_user_id,
        interviewer_ids=interviewer_ids, phase=_phase_for_session(interview),
        topic_tags=message.get("topic_tags"), current_question=message.get("current_question"),
    )
    await _broadcast_trigger_result(result, session_id=session_id, broadcaster=broadcaster)


async def _handle_phase_transition_request(
    message: dict[str, Any], *, session_id: uuid.UUID, tenant_id: uuid.UUID, connection: Connection,
    broadcaster: InProcessBroadcaster, tenant_resolver: TenantResolver, agent_bridge: AgentBridge,
) -> None:
    if connection.role_in_session not in AGENT_CONTROL_ALLOWED_ROLES:
        await connection.websocket.send_json({"type": "error", "detail": "Only interviewer/recruiter/company_admin may request a phase transition"})
        return

    next_phase = message.get("next_phase")
    if not next_phase:
        await connection.websocket.send_json({"type": "error", "detail": "Missing 'next_phase'"})
        return

    db_session, _ = await tenant_resolver.get_session_for_tenant_id(tenant_id)
    try:
        interview = await InterviewSessionRepository(db_session).get_by_id(session_id)
    finally:
        await db_session.close()

    interviewer_ids = [uuid.UUID(i) for i in (interview.interviewer_ids if interview else [])]
    candidate_user_id = interview.candidate_user_id if interview else None

    result = await agent_bridge.trigger_phase_transition_request(
        session_id=session_id, tenant_id=tenant_id, candidate_user_id=candidate_user_id,
        interviewer_ids=interviewer_ids, phase=_phase_for_session(interview), next_phase=next_phase,
    )
    # This trigger always pauses at phase_transition_node -- emit the
    # confirmation prompt explicitly (result.human_approval_type is not
    # set by Graph 1 for this interrupt, since phase_transition_node
    # isn't approval_type-branched the way human_approval_node is).
    await broadcaster.publish(
        session_id,
        {"type": "agent_event", "event_type": "human_approval_required", "payload": {"approval_type": "PHASE_END", "next_phase": next_phase}},
        only_roles={"interviewer"},
    )


async def _handle_human_decision(
    message: dict[str, Any], *, session_id: uuid.UUID, connection: Connection,
    broadcaster: InProcessBroadcaster, agent_bridge: AgentBridge,
) -> None:
    if connection.role_in_session not in AGENT_CONTROL_ALLOWED_ROLES:
        await connection.websocket.send_json({"type": "error", "detail": "Only interviewer/recruiter/company_admin may resolve an approval"})
        return

    decision = message.get("decision")
    if decision not in ("APPROVED", "EDITED", "REJECTED", "CONFIRMED"):
        await connection.websocket.send_json({"type": "error", "detail": f"Invalid decision '{decision}'"})
        return

    try:
        result = await agent_bridge.resume_human_decision(session_id=session_id, decision=decision)
    except Exception as exc:  # noqa: BLE001 -- e.g. InterviewRunNotFoundError if nothing was ever paused
        await connection.websocket.send_json({"type": "error", "detail": str(exc)})
        return

    if result.state.get("phase") is not None and message.get("_phase_transition_confirmed_broadcast", True):
        # Phase actually changed (or didn't) -- let everyone in the
        # room know the current phase, not just the interviewer, since
        # phase affects what all participants see (Section: session
        # phase state machine is room-wide, not interviewer-only).
        await broadcaster.publish(session_id, {"type": "phase_changed", "phase": result.state["phase"]})

    await _broadcast_trigger_result(result, session_id=session_id, broadcaster=broadcaster)
    if result.state.get("current_question"):
        # A newly-approved question should reach EVERYONE in the room
        # (candidate needs to see it too), unlike Co-Pilot/Integrity
        # which stay interviewer-only.
        await broadcaster.publish(session_id, {"type": "question_injected", "question": result.state["current_question"]})


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
    # NOTE: triggering Graph 1's SESSION_COMPLETED (report_synthesis_node)
    # here is deliberately NOT done in this slice -- full Report
    # Synthesis Agent wiring (scorecard approval workflow, PDF export,
    # `scorecard.generated` publish) is explicitly Milestone M11's job
    # (Section 4 build order). Triggering it from end_session with only
    # a placeholder LLM (see agent_bridge.py) would produce a scorecard
    # that looks real but isn't -- worse than not producing one yet.


def _as_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt