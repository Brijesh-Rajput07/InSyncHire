# LOCATION: services/user_profile_service/tests/test_application_submitted_consumer_service.py

"""
Proves the M5 addition: consuming application.submitted (published by
Job Service) creates the user_applications_index row, and a redelivery
doesn't duplicate it.
"""

import asyncio
import uuid

from insynchire_events.schemas import ApplicationSubmittedEvent
from shared.db import make_session_factory
from user_profile_service.models import UsersDbBase
from user_profile_service.repositories import ApplicationIndexRepository
from user_profile_service.services import ApplicationSubmittedConsumerService

from .conftest import build_test_engine


def test_handle_application_submitted_creates_index_row():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        application_id, user_id, tenant_id, job_id = (uuid.uuid4() for _ in range(4))
        service = ApplicationSubmittedConsumerService(users_db_session_factory=session_factory)

        event = ApplicationSubmittedEvent(
            trace_id="t1", tenant_id=tenant_id, application_id=application_id, job_id=job_id,
            candidate_user_id=user_id, resume_id=uuid.uuid4(),
        )
        await service.handle_application_submitted(event)

        async with session_factory() as session:
            index_row = await ApplicationIndexRepository(session).get_by_application_id(application_id)
            assert index_row is not None
            assert index_row.user_id == user_id
            assert index_row.tenant_id == tenant_id
            assert index_row.job_id == job_id
            assert index_row.current_stage == "applied"

        await engine.dispose()

    asyncio.run(_run())


def test_handle_application_submitted_is_idempotent_on_redelivery():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        application_id, user_id, tenant_id, job_id = (uuid.uuid4() for _ in range(4))
        service = ApplicationSubmittedConsumerService(users_db_session_factory=session_factory)
        event = ApplicationSubmittedEvent(
            trace_id="t1", tenant_id=tenant_id, application_id=application_id, job_id=job_id,
            candidate_user_id=user_id, resume_id=uuid.uuid4(),
        )

        await service.handle_application_submitted(event)
        await service.handle_application_submitted(event)  # redelivery

        async with session_factory() as session:
            from sqlalchemy import func, select
            from user_profile_service.models import UserApplicationIndex

            result = await session.execute(
                select(func.count()).select_from(UserApplicationIndex).where(
                    UserApplicationIndex.application_id == application_id
                )
            )
            assert result.scalar() == 1

        await engine.dispose()

    asyncio.run(_run())