# LOCATION: services/interview_service/tests/test_join_service.py

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from interview_service.models import TenantBase
from interview_service.services import (
    JoinInterviewNotFoundError,
    JoinService,
    NotAParticipantError,
    SchedulingService,
)
from shared.db import make_engine, make_session_factory

from .conftest import build_test_room_token_crypto, build_test_ws_token_service


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


def _build_engine():
    return make_engine("sqlite+aiosqlite:///:memory:")


def _future_time():
    return datetime.now(timezone.utc) + timedelta(days=2)


async def _schedule(session_factory, crypto, *, tenant_id, candidate_id, interviewer_ids, observer_ids):
    scheduling_service = SchedulingService(publish=FakePublisher().publish, room_token_crypto=crypto)
    async with session_factory() as session:
        return await scheduling_service.schedule_interview(
            session=session, tenant_id=tenant_id, scheduled_by=uuid.uuid4(),
            job_id=uuid.uuid4(), application_id=uuid.uuid4(), candidate_user_id=candidate_id,
            interviewer_ids=interviewer_ids, observer_ids=observer_ids,
            scheduled_at=_future_time(), trace_id="t1",
        )


def test_candidate_can_join_their_own_interview_and_gets_decrypted_room_token():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_room_token_crypto()
        tenant_id, candidate_id = uuid.uuid4(), uuid.uuid4()

        interview = await _schedule(
            session_factory, crypto, tenant_id=tenant_id, candidate_id=candidate_id,
            interviewer_ids=[uuid.uuid4()], observer_ids=[],
        )

        join_service = JoinService(room_token_crypto=crypto, ws_token_service=build_test_ws_token_service(crypto))
        async with session_factory() as session:
            result = await join_service.join(
                session, session_id=interview.session_id, tenant_id=tenant_id,
                user_id=candidate_id, role_in_session="candidate",
            )

        assert result.participant.role_in_session == "candidate"
        assert result.room_token is not None
        assert result.room_token == crypto.decrypt(interview.room_token)

        await engine.dispose()

    asyncio.run(_run())


def test_candidate_cannot_join_someone_elses_interview():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_room_token_crypto()
        tenant_id, real_candidate = uuid.uuid4(), uuid.uuid4()
        impostor = uuid.uuid4()

        interview = await _schedule(
            session_factory, crypto, tenant_id=tenant_id, candidate_id=real_candidate,
            interviewer_ids=[uuid.uuid4()], observer_ids=[],
        )

        join_service = JoinService(room_token_crypto=crypto, ws_token_service=build_test_ws_token_service(crypto))
        async with session_factory() as session:
            with pytest.raises(NotAParticipantError):
                await join_service.join(
                    session, session_id=interview.session_id, tenant_id=tenant_id,
                    user_id=impostor, role_in_session="candidate",
                )

        await engine.dispose()

    asyncio.run(_run())


def test_assigned_interviewer_can_join_but_unassigned_interviewer_cannot():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_room_token_crypto()
        tenant_id = uuid.uuid4()
        assigned, unassigned = uuid.uuid4(), uuid.uuid4()

        interview = await _schedule(
            session_factory, crypto, tenant_id=tenant_id, candidate_id=uuid.uuid4(),
            interviewer_ids=[assigned], observer_ids=[],
        )

        join_service = JoinService(room_token_crypto=crypto, ws_token_service=build_test_ws_token_service(crypto))

        async with session_factory() as session:
            result = await join_service.join(
                session, session_id=interview.session_id, tenant_id=tenant_id,
                user_id=assigned, role_in_session="interviewer",
            )
        assert result.participant.role_in_session == "interviewer"

        async with session_factory() as session:
            with pytest.raises(NotAParticipantError):
                await join_service.join(
                    session, session_id=interview.session_id, tenant_id=tenant_id,
                    user_id=unassigned, role_in_session="interviewer",
                )

        await engine.dispose()

    asyncio.run(_run())


def test_company_admin_and_recruiter_can_always_join_for_oversight():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_room_token_crypto()
        tenant_id = uuid.uuid4()

        interview = await _schedule(
            session_factory, crypto, tenant_id=tenant_id, candidate_id=uuid.uuid4(),
            interviewer_ids=[uuid.uuid4()], observer_ids=[],
        )

        join_service = JoinService(room_token_crypto=crypto, ws_token_service=build_test_ws_token_service(crypto))
        for role in ("company_admin", "recruiter"):
            async with session_factory() as session:
                result = await join_service.join(
                    session, session_id=interview.session_id, tenant_id=tenant_id,
                    user_id=uuid.uuid4(), role_in_session=role,
                )
                assert result.participant.role_in_session == role

        await engine.dispose()

    asyncio.run(_run())


def test_join_is_idempotent_does_not_duplicate_participant_row():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_room_token_crypto()
        tenant_id, candidate_id = uuid.uuid4(), uuid.uuid4()

        interview = await _schedule(
            session_factory, crypto, tenant_id=tenant_id, candidate_id=candidate_id,
            interviewer_ids=[uuid.uuid4()], observer_ids=[],
        )

        join_service = JoinService(room_token_crypto=crypto, ws_token_service=build_test_ws_token_service(crypto))
        async with session_factory() as session:
            first = await join_service.join(
                session, session_id=interview.session_id, tenant_id=tenant_id,
                user_id=candidate_id, role_in_session="candidate",
            )
        async with session_factory() as session:
            second = await join_service.join(
                session, session_id=interview.session_id, tenant_id=tenant_id,
                user_id=candidate_id, role_in_session="candidate",
            )

        assert first.participant.participant_id == second.participant.participant_id

        from interview_service.repositories import InterviewParticipantRepository

        async with session_factory() as session:
            participants = await InterviewParticipantRepository(session).list_for_session(interview.session_id)
        assert len(participants) == 1

        await engine.dispose()

    asyncio.run(_run())


def test_join_unknown_session_raises_not_found():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_room_token_crypto()
        join_service = JoinService(room_token_crypto=crypto, ws_token_service=build_test_ws_token_service(crypto))

        async with session_factory() as session:
            with pytest.raises(JoinInterviewNotFoundError):
                await join_service.join(
                    session, session_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
                    user_id=uuid.uuid4(), role_in_session="candidate",
                )

        await engine.dispose()

    asyncio.run(_run())