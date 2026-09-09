# LOCATION: services/user_profile_service/user_profile_service/services/notification_record_consumer_service.py

"""
M7 addition. Consumes the SAME Kafka topics the new Notification
Service (email-only) consumes, but writes the in-app
`users_db.user_notifications` row -- because `users_db` is owned by
THIS service (M4), not Notification Service, following the exact
no-cross-service-DB-writes precedent FIX-M2 established and M5's
`ApplicationSubmittedConsumerService` (in this same service) already
follows for `user_applications_index`.

*** SCOPE NOTE -- READ BEFORE EXTENDING ***
This milestone only wires up the THREE topics whose event payload
already carries a resolvable `user_id` directly:
  - `candidate.advanced` / `candidate.rejected`  -> candidate_user_id
  - `interview.scheduled`                        -> candidate_user_id
                                                     + interviewer_ids

`application.submitted` and `scorecard.generated` are DELIBERATELY NOT
handled here yet: Section 3 says these should notify "the recruiter" /
the hiring team, but resolving who that is requires reading
`tenant_user_memberships` in the tenant's own database -- this service
has no `TenantResolver` (it only ever reads `insynchire_global.global_users`
for the account_type check in `auth_dependency.py`). Notification
Service (the new M7 service) DOES have that tenant-DB read path already
built (see its `_get_recruiter_emails` helper) purely to know who to
email; duplicating that same tenant-DB-reading capability here just to
also write an in-app row is real scope, not a five-minute addition.

The clean long-term fix (left for a future milestone, not invented here
without being asked): either (a) give this service its own
`TenantResolver` too, mirroring Notification Service's, or (b) have
Notification Service publish a lightweight, already-resolved
notification-request event (`{user_id, type, title, body}` pairs) that
this service consumes purely to persist -- avoiding two services each
independently reading tenant DBs for the same purpose. Documented here
rather than silently left as a gap.

`agent.integrity_flagged` is not handled here either, for the same
reason it isn't fully handled in Notification Service: the event
carries no resolvable recipient user_id yet (see that service's
dispatch module for the full explanation).
"""

from __future__ import annotations

import logging
import uuid

from insynchire_events.schemas import CandidateAdvancedEvent, CandidateRejectedEvent, InterviewScheduledEvent

from ..repositories import NotificationRepository

logger = logging.getLogger("user_profile_service.notification_record_consumer")


class NotificationRecordConsumerService:
    def __init__(self, *, users_db_session_factory):
        self._session_factory = users_db_session_factory

    async def handle_candidate_advanced(self, event: CandidateAdvancedEvent) -> None:
        await self._write(
            user_id=event.candidate_user_id,
            type="candidate_advanced",
            title="Your application has advanced",
            body=f"Your application moved to stage: {event.new_stage}.",
        )

    async def handle_candidate_rejected(self, event: CandidateRejectedEvent) -> None:
        body = "Your application was not selected to move forward."
        if event.reason:
            body += f" Feedback: {event.reason}"
        await self._write(
            user_id=event.candidate_user_id, type="candidate_rejected", title="Update on your application", body=body,
        )

    async def handle_interview_scheduled(self, event: InterviewScheduledEvent) -> None:
        when = event.scheduled_at.isoformat()
        await self._write(
            user_id=event.candidate_user_id, type="interview_scheduled", title="Your interview is scheduled",
            body=f"Scheduled for {when}.",
        )
        for interviewer_id in event.interviewer_ids:
            await self._write(
                user_id=interviewer_id, type="interview_scheduled", title="You're scheduled to interview a candidate",
                body=f"Scheduled for {when}.",
            )

    async def _write(self, *, user_id: uuid.UUID, type: str, title: str, body: str) -> None:
        async with self._session_factory() as session:
            await NotificationRepository(session).create(user_id=user_id, type=type, title=title, body=body)
            await session.commit()
        logger.info("wrote user_notifications row type=%s user_id=%s", type, user_id)