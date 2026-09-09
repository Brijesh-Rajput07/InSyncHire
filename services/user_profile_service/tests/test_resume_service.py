# LOCATION: services/user_profile_service/tests/test_resume_service.py

import asyncio
import uuid

import pytest
from shared.db import make_session_factory
from user_profile_service.models import UsersDbBase
from user_profile_service.services import ResumeNotFoundError, ResumeOwnershipError, ResumeService

from .conftest import build_test_engine


def test_upload_resume_success():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        user_id = uuid.uuid4()
        service = ResumeService(users_db_session_factory=session_factory)

        resume = await service.upload_resume(
            user_id=user_id, file_url="https://files.example.com/r1.pdf",
            parsed_data={"skills": ["python"]}, is_primary=True,
        )
        assert resume.user_id == user_id
        assert resume.is_primary is True

        await engine.dispose()

    asyncio.run(_run())


def test_uploading_second_primary_unsets_first():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        user_id = uuid.uuid4()
        service = ResumeService(users_db_session_factory=session_factory)

        r1 = await service.upload_resume(user_id=user_id, file_url="r1.pdf", parsed_data=None, is_primary=True)
        r2 = await service.upload_resume(user_id=user_id, file_url="r2.pdf", parsed_data=None, is_primary=True)

        resumes = await service.list_resumes(user_id)
        by_id = {r.resume_id: r for r in resumes}
        assert by_id[r1.resume_id].is_primary is False
        assert by_id[r2.resume_id].is_primary is True

        await engine.dispose()

    asyncio.run(_run())


def test_select_primary_resume_success():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        user_id = uuid.uuid4()
        service = ResumeService(users_db_session_factory=session_factory)

        r1 = await service.upload_resume(user_id=user_id, file_url="r1.pdf", parsed_data=None, is_primary=False)
        r2 = await service.upload_resume(user_id=user_id, file_url="r2.pdf", parsed_data=None, is_primary=False)

        selected = await service.select_primary_resume(user_id=user_id, resume_id=r1.resume_id)
        assert selected.is_primary is True

        resumes = await service.list_resumes(user_id)
        by_id = {r.resume_id: r for r in resumes}
        assert by_id[r1.resume_id].is_primary is True
        assert by_id[r2.resume_id].is_primary is False

        await engine.dispose()

    asyncio.run(_run())


def test_select_primary_resume_not_found_raises():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        service = ResumeService(users_db_session_factory=session_factory)
        with pytest.raises(ResumeNotFoundError):
            await service.select_primary_resume(user_id=uuid.uuid4(), resume_id=uuid.uuid4())

        await engine.dispose()

    asyncio.run(_run())


def test_select_primary_resume_ownership_enforced():
    """A candidate must not be able to set another candidate's resume
    as primary, even if they guess/know the resume_id."""

    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        owner_id = uuid.uuid4()
        attacker_id = uuid.uuid4()
        service = ResumeService(users_db_session_factory=session_factory)

        owned_resume = await service.upload_resume(
            user_id=owner_id, file_url="r1.pdf", parsed_data=None, is_primary=False
        )

        with pytest.raises(ResumeOwnershipError):
            await service.select_primary_resume(user_id=attacker_id, resume_id=owned_resume.resume_id)

        await engine.dispose()

    asyncio.run(_run())