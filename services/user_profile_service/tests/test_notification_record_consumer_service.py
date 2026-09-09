# LOCATION: services/user_profile_service/tests/test_notification_record_consumer_service.py

"""
Proves the M7 addition: consuming candidate.advanced / candidate.rejected
/ interview.scheduled actually creates `user_notifications` rows --
the in-app half of Notification Service's (email-only) responsibility,
placed here because this service owns users_db (see
notification_record_consumer_service.py's module docstring for the
full DB-ownership reasoning and the documented application.submitted/
scorecard.generated scope gap).
"""

import asyncio
import uuid
from datetime import datetime, timezone

from insynchire_events.schemas import CandidateAdvancedEvent, CandidateRejectedEvent, InterviewScheduledEvent
from shared.db import make_session_factory
from sqlalchemy import select

from user_profile_service.models import UserNotification, UsersDbBase
from user_profile_service.services import NotificationRecordConsumerService

from .conftest import build_test_engine


def test_candidate_advanced_writes_notification_row():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        candidate_id, job_id = uuid.uuid4(), uuid.uuid4()
        service = NotificationRecordConsumerService(users_db_session_factory=session_factory)

        event = CandidateAdvancedEvent(
            trace_id="t1", tenant_id=uuid.uuid4(), application_id=uuid.uuid4(), job_id=job_id,
            candidate_user_id=candidate_id, new_stage="ADVANCED", advanced_by=uuid.uuid4(),
        )
        await service.handle_candidate_advanced(event)

        async with session_factory() as session:
            result = await session.execute(select(UserNotification).where(UserNotification.user_id == candidate_id))
            rows = result.scalars().all()
            assert len(rows) == 1
            assert rows[0].type == "candidate_advanced"
            assert "ADVANCED" in rows[0].body

        await engine.dispose()

    asyncio.run(_run())


def test_candidate_rejected_writes_notification_row_with_reason():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        candidate_id = uuid.uuid4()
        service = NotificationRecordConsumerService(users_db_session_factory=session_factory)

        event = CandidateRejectedEvent(
            trace_id="t1", tenant_id=uuid.uuid4(), application_id=uuid.uuid4(), job_id=uuid.uuid4(),
            candidate_user_id=candidate_id, rejected_by=uuid.uuid4(), reason="Not enough experience",
        )
        await service.handle_candidate_rejected(event)

        async with session_factory() as session:
            result = await session.execute(select(UserNotification).where(UserNotification.user_id == candidate_id))
            row = result.scalar_one()
            assert row.type == "candidate_rejected"
            assert "Not enough experience" in row.body

        await engine.dispose()

    asyncio.run(_run())


def test_interview_scheduled_writes_row_for_candidate_and_every_interviewer():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        candidate_id, interviewer_a, interviewer_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        service = NotificationRecordConsumerService(users_db_session_factory=session_factory)

        event = InterviewScheduledEvent(
            trace_id="t1", tenant_id=uuid.uuid4(), session_id=uuid.uuid4(), application_id=uuid.uuid4(),
            candidate_user_id=candidate_id, interviewer_ids=[interviewer_a, interviewer_b],
            scheduled_at=datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc),
        )
        await service.handle_interview_scheduled(event)

        async with session_factory() as session:
            result = await session.execute(select(UserNotification))
            rows = result.scalars().all()
            recipients = {row.user_id for row in rows}
            assert recipients == {candidate_id, interviewer_a, interviewer_b}
            assert len(rows) == 3

        await engine.dispose()

    asyncio.run(_run())


def test_notifications_are_independent_rows_not_overwritten():
    """Two separate events for the same user must produce two rows, not
    one row being updated -- a notification feed, not a single-slot
    status field."""

    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        candidate_id = uuid.uuid4()
        service = NotificationRecordConsumerService(users_db_session_factory=session_factory)

        await service.handle_candidate_advanced(
            CandidateAdvancedEvent(
                trace_id="t1", tenant_id=uuid.uuid4(), application_id=uuid.uuid4(), job_id=uuid.uuid4(),
                candidate_user_id=candidate_id, new_stage="ADVANCED", advanced_by=uuid.uuid4(),
            )
        )
        await service.handle_candidate_advanced(
            CandidateAdvancedEvent(
                trace_id="t2", tenant_id=uuid.uuid4(), application_id=uuid.uuid4(), job_id=uuid.uuid4(),
                candidate_user_id=candidate_id, new_stage="INTERVIEW_SCHEDULED", advanced_by=uuid.uuid4(),
            )
        )

        async with session_factory() as session:
            result = await session.execute(select(UserNotification).where(UserNotification.user_id == candidate_id))
            rows = result.scalars().all()
            assert len(rows) == 2

        await engine.dispose()

    asyncio.run(_run())