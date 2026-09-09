# LOCATION: services/interview_service/tests/test_scheduling_service.py

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from insynchire_events.topics import Topics
from interview_service.models import TenantBase
from interview_service.services import (
    InterviewAccessDeniedError,
    InterviewNotFoundError,
    SchedulingService,
)
from shared.db import make_engine, make_session_factory

from .conftest import build_test_room_token_crypto


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


def _build_engine():
    return make_engine("sqlite+aiosqlite:///:memory:")


def _future_time():
    return datetime.now(timezone.utc) + timedelta(days=2)


def test_schedule_interview_creates_session_and_publishes_event():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        publisher = FakePublisher()
        service = SchedulingService(publish=publisher.publish, room_token_crypto=build_test_room_token_crypto())

        tenant_id, scheduled_by = uuid.uuid4(), uuid.uuid4()
        job_id, application_id, candidate_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        interviewer_id, observer_id = uuid.uuid4(), uuid.uuid4()
        scheduled_at = _future_time()

        async with session_factory() as session:
            interview = await service.schedule_interview(
                session=session, tenant_id=tenant_id, scheduled_by=scheduled_by,
                job_id=job_id, application_id=application_id, candidate_user_id=candidate_id,
                interviewer_ids=[interviewer_id], observer_ids=[observer_id],
                scheduled_at=scheduled_at, trace_id="t1",
            )

        assert interview.status == "SCHEDULED"
        assert interview.interviewer_ids == [str(interviewer_id)]
        assert interview.observer_ids == [str(observer_id)]
        assert interview.room_token is not None
        assert interview.room_token != ""  # stored encrypted, not plaintext

        topics = [t for t, _ in publisher.published]
        assert Topics.INTERVIEW_SCHEDULED.value in topics
        _, event = publisher.published[0]
        assert event.session_id == interview.session_id
        assert event.candidate_user_id == candidate_id
        assert event.interviewer_ids == [interviewer_id]

        await engine.dispose()

    asyncio.run(_run())


def test_room_token_is_genuinely_encrypted_at_rest():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        crypto = build_test_room_token_crypto()
        service = SchedulingService(publish=FakePublisher().publish, room_token_crypto=crypto)

        async with session_factory() as session:
            interview = await service.schedule_interview(
                session=session, tenant_id=uuid.uuid4(), scheduled_by=uuid.uuid4(),
                job_id=uuid.uuid4(), application_id=uuid.uuid4(), candidate_user_id=uuid.uuid4(),
                interviewer_ids=[uuid.uuid4()], observer_ids=[], scheduled_at=_future_time(), trace_id="t1",
            )

        # The stored value must decrypt to a real opaque token, and must
        # not itself look like a plaintext secrets.token_urlsafe output
        # (i.e. it really went through Fernet, not just "stored as-is").
        decrypted = crypto.decrypt(interview.room_token)
        assert len(decrypted) > 20
        assert decrypted != interview.room_token

        await engine.dispose()

    asyncio.run(_run())


async def _seed_and_schedule(session_factory, *, tenant_id, interviewer_ids, observer_ids):
    service = SchedulingService(publish=FakePublisher().publish, room_token_crypto=build_test_room_token_crypto())
    async with session_factory() as session:
        return await service.schedule_interview(
            session=session, tenant_id=tenant_id, scheduled_by=uuid.uuid4(),
            job_id=uuid.uuid4(), application_id=uuid.uuid4(), candidate_user_id=uuid.uuid4(),
            interviewer_ids=interviewer_ids, observer_ids=observer_ids,
            scheduled_at=_future_time(), trace_id="t1",
        ), service


def test_get_session_for_staff_company_admin_sees_any_session():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        tenant_id = uuid.uuid4()

        interview, service = await _seed_and_schedule(
            session_factory, tenant_id=tenant_id, interviewer_ids=[uuid.uuid4()], observer_ids=[]
        )

        async with session_factory() as session:
            fetched = await service.get_session_for_staff(
                session, session_id=interview.session_id, tenant_id=tenant_id,
                requester_user_id=uuid.uuid4(), requester_role="company_admin",
            )
        assert fetched.session_id == interview.session_id

        await engine.dispose()

    asyncio.run(_run())


def test_get_session_for_staff_interviewer_denied_if_not_assigned():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        tenant_id = uuid.uuid4()
        assigned_interviewer = uuid.uuid4()
        outsider_interviewer = uuid.uuid4()

        interview, service = await _seed_and_schedule(
            session_factory, tenant_id=tenant_id, interviewer_ids=[assigned_interviewer], observer_ids=[]
        )

        async with session_factory() as session:
            with pytest.raises(InterviewAccessDeniedError):
                await service.get_session_for_staff(
                    session, session_id=interview.session_id, tenant_id=tenant_id,
                    requester_user_id=outsider_interviewer, requester_role="interviewer",
                )

        await engine.dispose()

    asyncio.run(_run())


def test_get_session_for_staff_assigned_interviewer_can_view():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        tenant_id = uuid.uuid4()
        assigned_interviewer = uuid.uuid4()

        interview, service = await _seed_and_schedule(
            session_factory, tenant_id=tenant_id, interviewer_ids=[assigned_interviewer], observer_ids=[]
        )

        async with session_factory() as session:
            fetched = await service.get_session_for_staff(
                session, session_id=interview.session_id, tenant_id=tenant_id,
                requester_user_id=assigned_interviewer, requester_role="interviewer",
            )
        assert fetched.session_id == interview.session_id

        await engine.dispose()

    asyncio.run(_run())


def test_get_session_for_staff_unknown_session_raises_not_found():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        service = SchedulingService(publish=FakePublisher().publish, room_token_crypto=build_test_room_token_crypto())

        async with session_factory() as session:
            with pytest.raises(InterviewNotFoundError):
                await service.get_session_for_staff(
                    session, session_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
                    requester_user_id=uuid.uuid4(), requester_role="company_admin",
                )

        await engine.dispose()

    asyncio.run(_run())


def test_get_session_for_staff_cross_tenant_lookup_raises_not_found():
    """A session_id that exists but belongs to a DIFFERENT tenant must
    404, not leak that it exists (defense in depth -- RLS would also
    catch this against real Postgres, but the repository-level tenant_id
    check is the second independent layer, Section 10b)."""

    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        real_tenant_id = uuid.uuid4()
        other_tenant_id = uuid.uuid4()

        interview, service = await _seed_and_schedule(
            session_factory, tenant_id=real_tenant_id, interviewer_ids=[uuid.uuid4()], observer_ids=[]
        )

        async with session_factory() as session:
            with pytest.raises(InterviewNotFoundError):
                await service.get_session_for_staff(
                    session, session_id=interview.session_id, tenant_id=other_tenant_id,
                    requester_user_id=uuid.uuid4(), requester_role="company_admin",
                )

        await engine.dispose()

    asyncio.run(_run())