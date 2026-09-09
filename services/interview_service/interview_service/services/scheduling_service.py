# LOCATION: services/interview_service/interview_service/services/scheduling_service.py

"""
Interview scheduling business logic (Section: STAGE 5 -- INTERVIEW
SCHEDULING).

`schedule_interview` creates the `interview_sessions` row
(status=SCHEDULED), mints and encrypts an opaque room token (Section
5's `room_token (encrypted)`; see `crypto.RoomTokenCrypto`'s module
docstring for why a real SFU room isn't minted yet), and publishes
`interview.scheduled` -- a topic + event schema that already existed in
`insynchire-events` before this milestone and is already consumed by
two services built in M7 (Notification Service sends the email;
`user_profile_service`'s `NotificationRecordConsumerService` writes the
in-app `user_notifications` row), so scheduling an interview here
"just works" against that existing pipeline with no changes needed on
either consumer.

`get_session_for_staff` is the authorization + lookup used by
`GET /interviews/{id}` (Section: RBAC ENFORCEMENT -- "Checked
server-side on EVERY endpoint"): `company_admin`/`recruiter` may view
any session in their tenant; `interviewer`/`observer` may only view
sessions they were actually assigned to (their user_id appears in
`interviewer_ids`/`observer_ids`) -- being any interviewer at the
company does not mean visibility into every other interviewer's
sessions.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from insynchire_events import Topics
from insynchire_events.schemas import InterviewScheduledEvent
from sqlalchemy.ext.asyncio import AsyncSession

from ..crypto import RoomTokenCrypto
from ..models import InterviewSession
from ..repositories import InterviewSessionRepository

STAFF_VIEW_ALL_ROLES = {"company_admin", "recruiter"}
STAFF_ASSIGNED_ONLY_ROLES = {"interviewer", "observer"}


class SchedulingError(Exception):
    """Base class for scheduling/lookup failures."""


class InterviewNotFoundError(SchedulingError):
    def __init__(self, session_id: uuid.UUID):
        super().__init__(f"Interview session {session_id} not found")


class InterviewAccessDeniedError(SchedulingError):
    def __init__(self):
        super().__init__("You are not assigned to this interview session")


class SchedulingService:
    def __init__(self, *, publish, room_token_crypto: RoomTokenCrypto):
        self._publish = publish
        self._room_token_crypto = room_token_crypto

    async def schedule_interview(
        self,
        *,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        scheduled_by: uuid.UUID,
        job_id: uuid.UUID,
        application_id: uuid.UUID,
        candidate_user_id: uuid.UUID,
        interviewer_ids: list[uuid.UUID],
        observer_ids: list[uuid.UUID],
        scheduled_at: datetime,
        trace_id: str,
    ) -> InterviewSession:
        plaintext_room_token = secrets.token_urlsafe(32)
        encrypted_room_token = self._room_token_crypto.encrypt(plaintext_room_token)

        interview = await InterviewSessionRepository(session).create(
            tenant_id=tenant_id,
            job_id=job_id,
            application_id=application_id,
            candidate_user_id=candidate_user_id,
            interviewer_ids=interviewer_ids,
            observer_ids=observer_ids,
            scheduled_at=scheduled_at,
            scheduled_by=scheduled_by,
            room_token=encrypted_room_token,
        )
        await session.commit()
        await session.refresh(interview)

        await self._publish(
            Topics.INTERVIEW_SCHEDULED.value,
            InterviewScheduledEvent(
                trace_id=trace_id,
                tenant_id=tenant_id,
                session_id=interview.session_id,
                application_id=application_id,
                candidate_user_id=candidate_user_id,
                interviewer_ids=interviewer_ids,
                observer_ids=observer_ids,
                scheduled_at=scheduled_at,
            ),
        )
        return interview

    async def get_session_for_staff(
        self,
        session: AsyncSession,
        *,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        requester_user_id: uuid.UUID,
        requester_role: str,
    ) -> InterviewSession:
        interview = await InterviewSessionRepository(session).get_by_id(session_id)
        if interview is None or interview.tenant_id != tenant_id:
            raise InterviewNotFoundError(session_id)

        if requester_role in STAFF_VIEW_ALL_ROLES:
            return interview

        if requester_role in STAFF_ASSIGNED_ONLY_ROLES:
            assigned_ids = (
                interview.interviewer_ids if requester_role == "interviewer" else interview.observer_ids
            )
            if str(requester_user_id) in assigned_ids:
                return interview

        raise InterviewAccessDeniedError()