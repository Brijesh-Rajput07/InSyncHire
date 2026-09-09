# LOCATION: services/job_service/tests/test_application_service.py

import asyncio
import uuid

import pytest
from insynchire_events.topics import Topics
from job_service.models import TenantBase
from job_service.services import (
    AlreadyAppliedError,
    ApplicationNotInThisOrgError,
    ApplicationService,
    JobNotOpenError,
    JobPostingService,
)
from shared.db import make_engine, make_session_factory


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


def _build_engine():
    return make_engine("sqlite+aiosqlite:///:memory:")


def _job_create_data(**overrides):
    base = dict(
        title="Backend Engineer", description="Build things", requirements=None, skills_tags=["python"],
        experience_level="senior", location="Remote", salary_min=None, salary_max=None,
    )
    base.update(overrides)
    return base


async def _seed_open_job(session_factory, *, tenant_id, org_id):
    posting_service = JobPostingService(publish=FakePublisher().publish)
    async with session_factory() as session:
        return await posting_service.create_job(
            session=session, tenant_id=tenant_id, org_id=org_id, posted_by=uuid.uuid4(),
            create_data=_job_create_data(), trace_id="t1",
        )


def test_submit_application_success_and_increments_count():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        tenant_id, org_id = uuid.uuid4(), uuid.uuid4()
        job = await _seed_open_job(session_factory, tenant_id=tenant_id, org_id=org_id)

        publisher = FakePublisher()
        service = ApplicationService(publish=publisher.publish)
        candidate_id = uuid.uuid4()

        async with session_factory() as session:
            application = await service.submit_application(
                session=session, tenant_id=tenant_id, job_id=job.job_id, candidate_user_id=candidate_id,
                resume_id=uuid.uuid4(), cover_note="I'm great", trace_id="t1",
            )

        assert application.status == "APPLIED"
        topics = [t for t, _ in publisher.published]
        assert Topics.APPLICATION_SUBMITTED.value in topics

        async with session_factory() as session:
            from job_service.repositories import JobOpeningRepository

            refreshed_job = await JobOpeningRepository(session).get_by_id(job.job_id)
            assert refreshed_job.application_count == 1

        await engine.dispose()

    asyncio.run(_run())


def test_duplicate_application_rejected():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        tenant_id, org_id = uuid.uuid4(), uuid.uuid4()
        job = await _seed_open_job(session_factory, tenant_id=tenant_id, org_id=org_id)

        service = ApplicationService(publish=FakePublisher().publish)
        candidate_id = uuid.uuid4()

        async with session_factory() as session:
            await service.submit_application(
                session=session, tenant_id=tenant_id, job_id=job.job_id, candidate_user_id=candidate_id,
                resume_id=None, cover_note=None, trace_id="t1",
            )

        async with session_factory() as session:
            with pytest.raises(AlreadyAppliedError):
                await service.submit_application(
                    session=session, tenant_id=tenant_id, job_id=job.job_id, candidate_user_id=candidate_id,
                    resume_id=None, cover_note=None, trace_id="t2",
                )

        await engine.dispose()

    asyncio.run(_run())


def test_apply_to_closed_job_rejected():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        tenant_id, org_id = uuid.uuid4(), uuid.uuid4()
        job = await _seed_open_job(session_factory, tenant_id=tenant_id, org_id=org_id)

        posting_service = JobPostingService(publish=FakePublisher().publish)
        async with session_factory() as session:
            await posting_service.close_job(session, job_id=job.job_id, org_id=org_id)

        service = ApplicationService(publish=FakePublisher().publish)
        async with session_factory() as session:
            with pytest.raises(JobNotOpenError):
                await service.submit_application(
                    session=session, tenant_id=tenant_id, job_id=job.job_id, candidate_user_id=uuid.uuid4(),
                    resume_id=None, cover_note=None, trace_id="t1",
                )

        await engine.dispose()

    asyncio.run(_run())


def test_advance_and_reject_publish_events():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        tenant_id, org_id = uuid.uuid4(), uuid.uuid4()
        job = await _seed_open_job(session_factory, tenant_id=tenant_id, org_id=org_id)

        publisher = FakePublisher()
        service = ApplicationService(publish=publisher.publish)
        candidate_a, candidate_b = uuid.uuid4(), uuid.uuid4()
        recruiter_id = uuid.uuid4()

        async with session_factory() as session:
            app_a = await service.submit_application(
                session=session, tenant_id=tenant_id, job_id=job.job_id, candidate_user_id=candidate_a,
                resume_id=None, cover_note=None, trace_id="t1",
            )
        async with session_factory() as session:
            app_b = await service.submit_application(
                session=session, tenant_id=tenant_id, job_id=job.job_id, candidate_user_id=candidate_b,
                resume_id=None, cover_note=None, trace_id="t2",
            )

        async with session_factory() as session:
            advanced = await service.advance(
                session, application_id=app_a.application_id, org_id=org_id, advanced_by=recruiter_id,
                tenant_id=tenant_id, trace_id="t3",
            )
            assert advanced.status == "ADVANCED"

        async with session_factory() as session:
            rejected = await service.reject(
                session, application_id=app_b.application_id, org_id=org_id, rejected_by=recruiter_id,
                tenant_id=tenant_id, reason="Not a fit", trace_id="t4",
            )
            assert rejected.status == "REJECTED"

        topics = [t for t, _ in publisher.published]
        assert Topics.CANDIDATE_ADVANCED.value in topics
        assert Topics.CANDIDATE_REJECTED.value in topics

        await engine.dispose()

    asyncio.run(_run())


def test_list_applicants_wrong_org_raises():
    async def _run():
        engine = _build_engine()
        async with engine.begin() as conn:
            await conn.run_sync(TenantBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        tenant_id, org_a, org_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        job = await _seed_open_job(session_factory, tenant_id=tenant_id, org_id=org_a)

        service = ApplicationService(publish=FakePublisher().publish)
        async with session_factory() as session:
            with pytest.raises(ApplicationNotInThisOrgError):
                await service.list_applicants(session, job_id=job.job_id, org_id=org_b)

        await engine.dispose()

    asyncio.run(_run())