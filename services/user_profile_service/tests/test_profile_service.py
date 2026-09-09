# LOCATION: services/user_profile_service/tests/test_profile_service.py

import asyncio
import uuid

from shared.db import make_session_factory
from user_profile_service.models import UsersDbBase
from user_profile_service.services import ProfileService

from .conftest import build_test_engine


def test_get_profile_auto_creates_blank_if_missing():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        user_id = uuid.uuid4()
        service = ProfileService(users_db_session_factory=session_factory)

        profile = await service.get_profile(user_id)
        assert profile.user_id == user_id
        assert profile.bio is None

        await engine.dispose()

    asyncio.run(_run())


def test_update_profile_applies_only_provided_fields():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        user_id = uuid.uuid4()
        service = ProfileService(users_db_session_factory=session_factory)

        await service.get_profile(user_id)  # ensure it exists first
        updated = await service.update_profile(user_id, {"bio": "Backend engineer", "experience_years": 5})
        assert updated.bio == "Backend engineer"
        assert updated.experience_years == 5
        assert updated.current_title is None  # untouched

        updated2 = await service.update_profile(user_id, {"current_title": "Staff Engineer"})
        assert updated2.current_title == "Staff Engineer"
        assert updated2.bio == "Backend engineer"  # still preserved

        await engine.dispose()

    asyncio.run(_run())


def test_update_profile_auto_creates_if_missing():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        user_id = uuid.uuid4()
        service = ProfileService(users_db_session_factory=session_factory)

        updated = await service.update_profile(user_id, {"location": "Remote"})
        assert updated.location == "Remote"

        await engine.dispose()

    asyncio.run(_run())