# LOCATION: services/notification_service/notification_service/services/notification_dispatch_service.py

"""
`NotificationDispatchService` -- one `handle_<event>` method per
notification-relevant topic named in Task N: `application.submitted`,
`candidate.advanced`, `candidate.rejected`, `interview.scheduled`,
`user.invited`, `scorecard.generated`, `agent.integrity_flagged`.

Each handler resolves the right recipient(s) (a direct email on the
event itself, a `global_users` lookup by `user_id`, or -- for
`application.submitted`/`scorecard.generated` -- every `company_admin`/
`recruiter` in the tenant via a read-only tenant-DB membership query)
and sends via the injected `EmailSender`. This service owns and writes
to no database at all -- see the module docstring in `config.py` and
README.md's "DB ownership" section for why the corresponding
`users_db.user_notifications` row-writes live in `user_profile_service`
instead.

KNOWN GAP -- `agent.integrity_flagged`: Section 3 says this should alert
"the interviewer", but `AgentIntegrityFlaggedEvent` (insynchire-events,
FIX-M0) carries only `tenant_id`/`session_id`/`signal_type`/
`confidence_score` -- no `interviewer_ids`. Resolving the actual
interviewer(s) would require reading `interview_sessions`, a tenant-DB
table that doesn't exist until Interview Service (M8). Until then this
handler logs a WARNING (visible in ops output) and does not send an
email -- silently dropping it would be worse than a loud, documented
no-op. Revisit once M8 either extends the event with `interviewer_ids`
or this service gains a read path to `interview_sessions`.
"""

from __future__ import annotations

import logging
import uuid

from insynchire_events.schemas import (
    AgentIntegrityFlaggedEvent,
    ApplicationSubmittedEvent,
    CandidateAdvancedEvent,
    CandidateRejectedEvent,
    InterviewScheduledEvent,
    ScorecardGeneratedEvent,
    UserInvitedEvent,
)

from ..email import EmailMessage, EmailSender
from ..email import templates
from ..repositories import GlobalTenantRepository, GlobalUserRepository, JobOpeningRepository, MembershipRepository
from ..tenant_db import TenantNotActiveError, TenantNotFoundError, TenantResolver

logger = logging.getLogger("notification_service.dispatch")

RECRUITER_ROLES = ["company_admin", "recruiter"]


class NotificationDispatchService:
    def __init__(
        self,
        *,
        email_sender: EmailSender,
        global_tenant_repository: GlobalTenantRepository,
        global_user_repository: GlobalUserRepository,
        tenant_resolver: TenantResolver,
    ):
        self._email_sender = email_sender
        self._global_tenant_repository = global_tenant_repository
        self._global_user_repository = global_user_repository
        self._tenant_resolver = tenant_resolver

    async def _send(self, to_address: str | None, subject: str, body: str) -> None:
        if not to_address:
            return
        await self._email_sender.send(EmailMessage(to_address=to_address, subject=subject, body=body))

    async def _get_recruiter_emails(self, tenant_id: uuid.UUID) -> list[str]:
        """Resolves every `company_admin`/`recruiter` in a tenant to an
        email address. Returns an empty list (logged) if the tenant
        can't be reached -- a notification-delivery problem must never
        crash the consumer or block other events."""
        try:
            session, _ = await self._tenant_resolver.get_session_for_tenant_id(tenant_id)
        except (TenantNotFoundError, TenantNotActiveError) as exc:
            logger.warning("could not resolve recruiters for tenant_id=%s: %s", tenant_id, exc)
            return []
        try:
            user_ids = await MembershipRepository(session).list_user_ids_for_roles(tenant_id, RECRUITER_ROLES)
        finally:
            await session.close()
        return await self._global_user_repository.get_emails(user_ids)

    async def _get_job_title(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> str | None:
        try:
            session, _ = await self._tenant_resolver.get_session_for_tenant_id(tenant_id)
        except (TenantNotFoundError, TenantNotActiveError) as exc:
            logger.warning("could not resolve job title for tenant_id=%s job_id=%s: %s", tenant_id, job_id, exc)
            return None
        try:
            return await JobOpeningRepository(session).get_title(job_id)
        finally:
            await session.close()

    # ── user.invited ─────────────────────────────────────────────────
    async def handle_user_invited(self, event: UserInvitedEvent) -> None:
        try:
            tenant = await self._global_tenant_repository.get_by_id(event.tenant_id)
            tenant_name = tenant.company_name
        except Exception:  # noqa: BLE001 -- a missing tenant name shouldn't block the invite email
            tenant_name = "your new team"
        subject, body = templates.user_invited(tenant_name=tenant_name, role=event.role)
        await self._send(event.email, subject, body)

    # ── application.submitted ───────────────────────────────────────
    async def handle_application_submitted(self, event: ApplicationSubmittedEvent) -> None:
        job_title = await self._get_job_title(event.tenant_id, event.job_id) or "a job opening"
        subject, body = templates.application_submitted_recruiter_alert(job_title=job_title)
        recruiter_emails = await self._get_recruiter_emails(event.tenant_id)
        for email in recruiter_emails:
            await self._send(email, subject, body)

    # ── candidate.advanced ──────────────────────────────────────────
    async def handle_candidate_advanced(self, event: CandidateAdvancedEvent) -> None:
        job_title = await self._get_job_title(event.tenant_id, event.job_id) or "your application"
        subject, body = templates.candidate_advanced(job_title=job_title, new_stage=event.new_stage)
        email = await self._resolve_user_email(event.candidate_user_id)
        await self._send(email, subject, body)

    # ── candidate.rejected ──────────────────────────────────────────
    async def handle_candidate_rejected(self, event: CandidateRejectedEvent) -> None:
        job_title = await self._get_job_title(event.tenant_id, event.job_id) or "your application"
        subject, body = templates.candidate_rejected(job_title=job_title, reason=event.reason)
        email = await self._resolve_user_email(event.candidate_user_id)
        await self._send(email, subject, body)

    # ── interview.scheduled ─────────────────────────────────────────
    async def handle_interview_scheduled(self, event: InterviewScheduledEvent) -> None:
        candidate_subject, candidate_body = templates.interview_scheduled_candidate(scheduled_at=event.scheduled_at)
        candidate_email = await self._resolve_user_email(event.candidate_user_id)
        await self._send(candidate_email, candidate_subject, candidate_body)

        interviewer_subject, interviewer_body = templates.interview_scheduled_interviewer(
            scheduled_at=event.scheduled_at
        )
        interviewer_emails = await self._global_user_repository.get_emails(event.interviewer_ids)
        for email in interviewer_emails:
            await self._send(email, interviewer_subject, interviewer_body)

    # ── scorecard.generated ─────────────────────────────────────────
    async def handle_scorecard_generated(self, event: ScorecardGeneratedEvent) -> None:
        subject, body = templates.scorecard_generated_recruiter_alert(
            overall_recommendation=event.overall_recommendation
        )
        recruiter_emails = await self._get_recruiter_emails(event.tenant_id)
        for email in recruiter_emails:
            await self._send(email, subject, body)

    # ── agent.integrity_flagged ─────────────────────────────────────
    async def handle_agent_integrity_flagged(self, event: AgentIntegrityFlaggedEvent) -> None:
        """KNOWN GAP -- see module docstring. Logs loudly, sends nothing."""
        logger.warning(
            "agent.integrity_flagged received for session_id=%s (signal_type=%s) but this event carries no "
            "interviewer_ids -- cannot resolve a recipient yet (blocked on Interview Service / M8). Skipping.",
            event.session_id, event.signal_type,
        )

    async def _resolve_user_email(self, user_id: uuid.UUID) -> str | None:
        try:
            return await self._global_user_repository.get_email(user_id)
        except Exception as exc:  # noqa: BLE001 -- a missing user shouldn't crash the consumer
            logger.warning("could not resolve email for user_id=%s: %s", user_id, exc)
            return None