# LOCATION: services/interview_service/interview_service/services/join_service.py

"""
Interview room join logic (Section: STAGE 6 -- LIVE INTERVIEW ROOM, the
join/authorization half of it -- the actual WebSocket gateway, Yjs sync,
video, and agent panels are M9/M10, out of scope here).

`join` authorizes the caller against the session's actual assignment
(candidate must BE the session's candidate; interviewer/observer must
be IN interviewer_ids/observer_ids; company_admin/recruiter may always
join for oversight, matching `PERMISSION_MATRIX`'s
`POST /interviews/{id}/join` entry listing all five roles), records an
idempotent `interview_participants` row (Section: interview_participants
-- "session_id, user_id, role_in_session, joined_at, left_at"), and
returns two DIFFERENT tokens the caller needs next:

  - `room_token`: the session-wide opaque token (decrypted from
    `interview_sessions.room_token`), for a future SFU/video
    integration (Section 10f) -- same value for every participant.
  - `ws_connect_token` (M9): a per-participant, short-lived signed
    token (`ws_tokens.WSConnectTokenService`) the caller passes as a
    query parameter when opening the WebSocket connection to THIS
    service's own live-room gateway (`ws_gateway.py`) for chat, the
    collaborative code editor, and (later) agent event delivery. See
    `ws_tokens.py`'s module docstring for why these are two separate
    tokens rather than one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..crypto import RoomTokenCrypto
from ..models import InterviewParticipant, InterviewSession
from ..repositories import InterviewParticipantRepository, InterviewSessionRepository
from ..ws_tokens import WSConnectTokenService

STAFF_ALWAYS_ALLOWED_ROLES = {"company_admin", "recruiter"}


class JoinError(Exception):
    """Base class for join failures."""


class InterviewNotFoundError(JoinError):
    def __init__(self, session_id: uuid.UUID):
        super().__init__(f"Interview session {session_id} not found")


class NotAParticipantError(JoinError):
    def __init__(self):
        super().__init__("You are not a participant in this interview session")


@dataclass
class JoinResult:
    session: InterviewSession
    participant: InterviewParticipant
    room_token: str | None
    ws_connect_token: str


class JoinService:
    def __init__(self, *, room_token_crypto: RoomTokenCrypto, ws_token_service: WSConnectTokenService):
        self._room_token_crypto = room_token_crypto
        self._ws_token_service = ws_token_service

    def _is_authorized(self, interview: InterviewSession, *, user_id: uuid.UUID, role_in_session: str) -> bool:
        if role_in_session in STAFF_ALWAYS_ALLOWED_ROLES:
            return True
        if role_in_session == "candidate":
            return interview.candidate_user_id == user_id
        if role_in_session == "interviewer":
            return str(user_id) in interview.interviewer_ids
        if role_in_session == "observer":
            return str(user_id) in interview.observer_ids
        return False

    async def join(
        self,
        session: AsyncSession,
        *,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        role_in_session: str,
    ) -> JoinResult:
        interview = await InterviewSessionRepository(session).get_by_id(session_id)
        if interview is None or interview.tenant_id != tenant_id:
            raise InterviewNotFoundError(session_id)

        if not self._is_authorized(interview, user_id=user_id, role_in_session=role_in_session):
            raise NotAParticipantError()

        participant = await InterviewParticipantRepository(session).create_or_touch(
            tenant_id=tenant_id, session_id=session_id, user_id=user_id, role_in_session=role_in_session
        )
        await session.commit()
        await session.refresh(participant)

        room_token = self._room_token_crypto.decrypt(interview.room_token) if interview.room_token else None
        ws_connect_token = self._ws_token_service.issue(
            tenant_id=tenant_id, session_id=session_id, user_id=user_id, role_in_session=role_in_session
        )
        return JoinResult(
            session=interview, participant=participant, room_token=room_token, ws_connect_token=ws_connect_token
        )