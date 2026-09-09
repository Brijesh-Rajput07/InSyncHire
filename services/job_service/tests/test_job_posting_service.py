# LOCATION: services/job_service/tests/test_job_posting_service.py

import asyncio
import uuid

import pytest
from insynchire_events.topics import Topics
from job_service.models import TenantBase
from job_service.services import JobNotFoundError, JobNotInThisOrgError, JobPostingService
from shared.db import make_engine, make_session_factory


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


def _build_engine():
    return make_engine("sqlite+aiosqlite:///:memory:")


def _create_data(**overrides):
    base = dict(
        title="Backend Engineer", description="Build things", requirements=None, skills_tags=["python"],
        experience_level="senior", location="Remote", salary_min=100000, salary_max=150000,
    )
    base.update(overrides)
    return base


def test_create_job_publishes_job_posted():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        publisher = FakePublisher()
        service = JobPostingService(publish=publisher.publish)

        tenant_id, org_id, posted_by = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with session_factory() as session:
            job = await service.create_job(
                session=session, tenant_id=tenant_id, org_id=org_id, posted_by=posted_by,
                create_data=_create_data(), trace_id="t1",
            )

        assert job.title == "Backend Engineer"
        assert job.status == "OPEN"
        assert job.application_count == 0
        topics = [t for t, _ in publisher.published]
        assert Topics.JOB_POSTED.value in topics

        await engine.dispose()

    asyncio.run(_run())


def test_list_jobs_scoped_to_org():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        service = JobPostingService(publish=FakePublisher().publish)
        tenant_id = uuid.uuid4()
        org_a, org_b = uuid.uuid4(), uuid.uuid4()

        async with session_factory() as session:
            await service.create_job(
                session=session, tenant_id=tenant_id, org_id=org_a, posted_by=uuid.uuid4(),
                create_data=_create_data(title="Job A"), trace_id="t1",
            )
            await service.create_job(
                session=session, tenant_id=tenant_id, org_id=org_b, posted_by=uuid.uuid4(),
                create_data=_create_data(title="Job B"), trace_id="t2",
            )

        async with session_factory() as session:
            jobs = await service.list_jobs(session, org_id=org_a)
            assert len(jobs) == 1
            assert jobs[0].title == "Job A"

        await engine.dispose()

    asyncio.run(_run())


def test_get_job_wrong_org_raises():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        service = JobPostingService(publish=FakePublisher().publish)
        tenant_id, org_a, org_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        async with session_factory() as session:
            job = await service.create_job(
                session=session, tenant_id=tenant_id, org_id=org_a, posted_by=uuid.uuid4(),
                create_data=_create_data(), trace_id="t1",
            )

        async with session_factory() as session:
            with pytest.raises(JobNotInThisOrgError):
                await service.get_job(session, job_id=job.job_id, org_id=org_b)

        await engine.dispose()

    asyncio.run(_run())


def test_get_unknown_job_raises_not_found():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        service = JobPostingService(publish=FakePublisher().publish)
        async with session_factory() as session:
            with pytest.raises(JobNotFoundError):
                await service.get_job(session, job_id=uuid.uuid4(), org_id=uuid.uuid4())

        await engine.dispose()

    asyncio.run(_run())


def test_update_job_partial_update():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        service = JobPostingService(publish=FakePublisher().publish)
        tenant_id, org_id = uuid.uuid4(), uuid.uuid4()

        async with session_factory() as session:
            job = await service.create_job(
                session=session, tenant_id=tenant_id, org_id=org_id, posted_by=uuid.uuid4(),
                create_data=_create_data(), trace_id="t1",
            )

        async with session_factory() as session:
            updated = await service.update_job(
                session, job_id=job.job_id, org_id=org_id, update_data={"title": "Staff Engineer"}
            )
            assert updated.title == "Staff Engineer"
            assert updated.location == "Remote"  # untouched

        await engine.dispose()

    asyncio.run(_run())


def test_close_job_sets_status_and_closed_at():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        service = JobPostingService(publish=FakePublisher().publish)
        tenant_id, org_id = uuid.uuid4(), uuid.uuid4()

        async with session_factory() as session:
            job = await service.create_job(
                session=session, tenant_id=tenant_id, org_id=org_id, posted_by=uuid.uuid4(),
                create_data=_create_data(), trace_id="t1",
            )

        async with session_factory() as session:
            closed = await service.close_job(session, job_id=job.job_id, org_id=org_id)
            assert closed.status == "CLOSED"
            assert closed.closed_at is not None

        await engine.dispose()

    asyncio.run(_run())