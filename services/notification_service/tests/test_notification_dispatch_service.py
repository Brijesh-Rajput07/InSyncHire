# LOCATION: services/notification_service/tests/test_notification_dispatch_service.py

"""
Integration tests for `NotificationDispatchService`: proves recipient
resolution actually works against a real (temp-file SQLite) tenant DB
for the org-side recruiter lookup, a real insynchire_global for
candidate/interviewer email lookups, and that each of the 7 handlers
sends to the right people (or, for `agent.integrity_flagged`, sends
nothing and logs instead -- see the module docstring in
notification_dispatch_service.py for why).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from insynchire_events.schemas import (
    AgentIntegrityFlaggedEvent,
    ApplicationSubmittedEvent,
    CandidateAdvancedEvent,
    CandidateRejectedEvent,
    InterviewScheduledEvent,
    ScorecardGeneratedEvent,
    UserInvitedEvent,
)
from shared.db import make_session_factory

from notification_service.email import ConsoleEmailSender
from notification_service.models import GlobalBase, JobOpening, TenantUserMembership
from notification_service.repositories import GlobalTenantRepository, GlobalUserRepository
from notification_service.services import NotificationDispatchService
from notification_service.tenant_db import TenantResolver

from .conftest import build_global_test_engine, build_test_crypto, seed_active_tenant, seed_global_user


async def _seed_membership(tenant_resolver, tenant_id, *, user_id, role):
    session, _ = await tenant_resolver.get_session_for_tenant_id(tenant_id)
    try:
        session.add(TenantUserMembership(membership_id=uuid.uuid4(), user_id=user_id, tenant_id=tenant_id, role=role))
        await session.commit()
    finally:
        await session.close()


async def _seed_job_opening(tenant_resolver, tenant_id, *, job_id, title):
    session, _ = await tenant_resolver.get_session_for_tenant_id(tenant_id)
    try:
        session.add(JobOpening(job_id=job_id, title=title))
        await session.commit()
    finally:
        await session.close()


def _build_service(*, global_session_factory, tenant_resolver):
    sender = ConsoleEmailSender()
    service = NotificationDispatchService(
        email_sender=sender,
        global_tenant_repository=GlobalTenantRepository(global_session_factory),
        global_user_repository=GlobalUserRepository(global_session_factory),
        tenant_resolver=tenant_resolver,
    )
    return service, sender


def test_user_invited_sends_directly_to_event_email_with_tenant_name():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        tenant = await seed_active_tenant(session_factory, crypto, company_name="Acme Corp")
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
        service, sender = _build_service(global_session_factory=session_factory, tenant_resolver=resolver)

        event = UserInvitedEvent(
            trace_id="t1", invite_id=uuid.uuid4(), email="newhire@acme-corp.com", role="recruiter",
            invited_by=uuid.uuid4(), tenant_id=tenant.tenant_id,
        )
        await service.handle_user_invited(event)

        assert len(sender.sent) == 1
        assert sender.sent[0].to_address == "newhire@acme-corp.com"
        assert "Acme Corp" in sender.sent[0].subject

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_application_submitted_notifies_all_recruiters_and_admins_only():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        tenant = await seed_active_tenant(session_factory, crypto)
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
        service, sender = _build_service(global_session_factory=session_factory, tenant_resolver=resolver)

        admin_id, recruiter_id, interviewer_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await seed_global_user(session_factory, admin_id, email="admin@acme-corp.com", account_type="company_user")
        await seed_global_user(session_factory, recruiter_id, email="recruiter@acme-corp.com", account_type="company_user")
        await seed_global_user(session_factory, interviewer_id, email="interviewer@acme-corp.com", account_type="company_user")

        await _seed_membership(resolver, tenant.tenant_id, user_id=admin_id, role="company_admin")
        await _seed_membership(resolver, tenant.tenant_id, user_id=recruiter_id, role="recruiter")
        await _seed_membership(resolver, tenant.tenant_id, user_id=interviewer_id, role="interviewer")

        job_id = uuid.uuid4()
        await _seed_job_opening(resolver, tenant.tenant_id, job_id=job_id, title="Backend Engineer")

        event = ApplicationSubmittedEvent(
            trace_id="t1", tenant_id=tenant.tenant_id, application_id=uuid.uuid4(), job_id=job_id,
            candidate_user_id=uuid.uuid4(), resume_id=uuid.uuid4(),
        )
        await service.handle_application_submitted(event)

        recipients = {m.to_address for m in sender.sent}
        assert recipients == {"admin@acme-corp.com", "recruiter@acme-corp.com"}
        assert all("Backend Engineer" in m.subject for m in sender.sent)

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_candidate_advanced_notifies_only_the_candidate():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        tenant = await seed_active_tenant(session_factory, crypto)
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
        service, sender = _build_service(global_session_factory=session_factory, tenant_resolver=resolver)

        candidate_id = uuid.uuid4()
        await seed_global_user(session_factory, candidate_id, email="candidate@example.com")
        job_id = uuid.uuid4()
        await _seed_job_opening(resolver, tenant.tenant_id, job_id=job_id, title="Backend Engineer")

        event = CandidateAdvancedEvent(
            trace_id="t1", tenant_id=tenant.tenant_id, application_id=uuid.uuid4(), job_id=job_id,
            candidate_user_id=candidate_id, new_stage="ADVANCED", advanced_by=uuid.uuid4(),
        )
        await service.handle_candidate_advanced(event)

        assert len(sender.sent) == 1
        assert sender.sent[0].to_address == "candidate@example.com"
        assert "Backend Engineer" in sender.sent[0].subject

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_candidate_rejected_includes_reason_and_notifies_candidate():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        tenant = await seed_active_tenant(session_factory, crypto)
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
        service, sender = _build_service(global_session_factory=session_factory, tenant_resolver=resolver)

        candidate_id = uuid.uuid4()
        await seed_global_user(session_factory, candidate_id, email="candidate@example.com")
        job_id = uuid.uuid4()
        await _seed_job_opening(resolver, tenant.tenant_id, job_id=job_id, title="Backend Engineer")

        event = CandidateRejectedEvent(
            trace_id="t1", tenant_id=tenant.tenant_id, application_id=uuid.uuid4(), job_id=job_id,
            candidate_user_id=candidate_id, rejected_by=uuid.uuid4(), reason="Not enough experience",
        )
        await service.handle_candidate_rejected(event)

        assert len(sender.sent) == 1
        assert "Not enough experience" in sender.sent[0].body

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_interview_scheduled_notifies_candidate_and_every_interviewer():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        tenant = await seed_active_tenant(session_factory, crypto)
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
        service, sender = _build_service(global_session_factory=session_factory, tenant_resolver=resolver)

        candidate_id, interviewer_a, interviewer_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await seed_global_user(session_factory, candidate_id, email="candidate@example.com")
        await seed_global_user(session_factory, interviewer_a, email="interviewer_a@acme-corp.com", account_type="company_user")
        await seed_global_user(session_factory, interviewer_b, email="interviewer_b@acme-corp.com", account_type="company_user")

        event = InterviewScheduledEvent(
            trace_id="t1", tenant_id=tenant.tenant_id, session_id=uuid.uuid4(), application_id=uuid.uuid4(),
            candidate_user_id=candidate_id, interviewer_ids=[interviewer_a, interviewer_b],
            scheduled_at=datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc),
        )
        await service.handle_interview_scheduled(event)

        recipients = {m.to_address for m in sender.sent}
        assert recipients == {"candidate@example.com", "interviewer_a@acme-corp.com", "interviewer_b@acme-corp.com"}

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_scorecard_generated_notifies_recruiters_with_recommendation():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        tenant = await seed_active_tenant(session_factory, crypto)
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
        service, sender = _build_service(global_session_factory=session_factory, tenant_resolver=resolver)

        recruiter_id = uuid.uuid4()
        await seed_global_user(session_factory, recruiter_id, email="recruiter@acme-corp.com", account_type="company_user")
        await _seed_membership(resolver, tenant.tenant_id, user_id=recruiter_id, role="recruiter")

        event = ScorecardGeneratedEvent(
            trace_id="t1", tenant_id=tenant.tenant_id, scorecard_id=uuid.uuid4(), session_id=uuid.uuid4(),
            candidate_user_id=uuid.uuid4(), overall_recommendation="STRONG_YES", is_final=True,
        )
        await service.handle_scorecard_generated(event)

        assert len(sender.sent) == 1
        assert sender.sent[0].to_address == "recruiter@acme-corp.com"
        assert "STRONG_YES" in sender.sent[0].body

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_agent_integrity_flagged_sends_nothing_documented_gap(caplog):
    """KNOWN GAP: no interviewer_ids on this event yet -- see the
    handler's docstring. Must not crash, must not send email."""

    async def _run():
        import logging

        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
        service, sender = _build_service(global_session_factory=session_factory, tenant_resolver=resolver)

        event = AgentIntegrityFlaggedEvent(
            trace_id="t1", tenant_id=uuid.uuid4(), session_id=uuid.uuid4(),
            signal_type="paste_burst", confidence_score=0.9,
        )
        with caplog.at_level(logging.WARNING, logger="notification_service.dispatch"):
            await service.handle_agent_integrity_flagged(event)

        assert sender.sent == []
        assert "cannot resolve a recipient" in caplog.text

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_recruiter_resolution_degrades_gracefully_for_unknown_tenant():
    """A tenant lookup failure must not crash the consumer -- just no
    recipients resolved (logged)."""

    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
        service, sender = _build_service(global_session_factory=session_factory, tenant_resolver=resolver)

        event = ApplicationSubmittedEvent(
            trace_id="t1", tenant_id=uuid.uuid4(), application_id=uuid.uuid4(), job_id=uuid.uuid4(),
            candidate_user_id=uuid.uuid4(), resume_id=uuid.uuid4(),
        )
        await service.handle_application_submitted(event)  # tenant doesn't exist -- must not raise
        assert sender.sent == []

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())