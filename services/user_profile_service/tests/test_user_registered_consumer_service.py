# LOCATION: services/user_profile_service/tests/test_user_registered_consumer_service.py

"""
Proves the core M4 fix: consuming user.registered actually creates the
user_profiles row that FIX-M2 removed from Auth Service's direct write.
"""

import asyncio
import uuid

from insynchire_events.schemas import UserRegisteredEvent
from shared.db import make_session_factory
from user_profile_service.models import UsersDbBase
from user_profile_service.repositories import ProfileRepository
from user_profile_service.services import UserRegisteredConsumerService

from .conftest import build_test_engine


def test_handle_user_registered_creates_profile_for_candidate():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        user_id = uuid.uuid4()
        service = UserRegisteredConsumerService(users_db_session_factory=session_factory)

        event = UserRegisteredEvent(trace_id="t1", user_id=user_id, email="jane@example.com", account_type="candidate")
        await service.handle_user_registered(event)

        async with session_factory() as session:
            profile = await ProfileRepository(session).get_by_user_id(user_id)
            assert profile is not None
            assert profile.user_id == user_id
            assert profile.bio is None  # blank profile

        await engine.dispose()

    asyncio.run(_run())


def test_handle_user_registered_skips_company_user():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        user_id = uuid.uuid4()
        service = UserRegisteredConsumerService(users_db_session_factory=session_factory)

        event = UserRegisteredEvent(
            trace_id="t1", user_id=user_id, email="alice@acme.com", account_type="company_user"
        )
        await service.handle_user_registered(event)

        async with session_factory() as session:
            profile = await ProfileRepository(session).get_by_user_id(user_id)
            assert profile is None

        await engine.dispose()

    asyncio.run(_run())


def test_handle_user_registered_is_idempotent_on_redelivery():
    """Kafka at-least-once semantics -- a redelivered user.registered
    must not crash or duplicate the profile row."""

    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        user_id = uuid.uuid4()
        service = UserRegisteredConsumerService(users_db_session_factory=session_factory)
        event = UserRegisteredEvent(trace_id="t1", user_id=user_id, email="jane@example.com", account_type="candidate")

        await service.handle_user_registered(event)
        await service.handle_user_registered(event)  # redelivery

        async with session_factory() as session:
            from sqlalchemy import select, func
            from user_profile_service.models import UserProfile

            result = await session.execute(
                select(func.count()).select_from(UserProfile).where(UserProfile.user_id == user_id)
            )
            assert result.scalar() == 1

        await engine.dispose()

    asyncio.run(_run())