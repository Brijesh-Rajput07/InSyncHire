# LOCATION: services/job_service/tests/test_public_board_service.py

"""
Tests PublicBoardService against REAL temp-file SQLite tenant DBs
(same "genuinely exercise the decrypt-then-connect path" philosophy as
tenant_service's tests) -- proves the interim cross-tenant scan
actually aggregates OPEN jobs from multiple tenants and skips CLOSED
ones, not just that the method returns something.
"""

import asyncio
import uuid

from job_service.models import GlobalBase
from job_service.repositories import JobOpeningRepository
from job_service.services import PublicBoardService
from job_service.tenant_db import TenantResolver
from shared.db import make_session_factory

from .conftest import build_global_test_engine, build_test_crypto, seed_active_tenant


async def _seed_job(tenant_resolver, tenant_id, *, title, status="OPEN"):
    session, _ = await tenant_resolver.get_session_for_tenant_id(tenant_id)
    try:
        job = await JobOpeningRepository(session).create(
            tenant_id=tenant_id, org_id=uuid.uuid4(), title=title, description="desc",
            requirements=None, skills_tags=["python"], experience_level=None, location=None,
            salary_min=None, salary_max=None, posted_by=uuid.uuid4(),
        )
        if status == "CLOSED":
            await JobOpeningRepository(session).close(job)
        await session.commit()
    finally:
        await session.close()


def test_list_open_jobs_aggregates_across_tenants_and_skips_closed():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        tenant_a = await seed_active_tenant(
            session_factory, crypto, subdomain="acme", company_name="Acme", company_domain="acme-corp.com"
        )
        tenant_b = await seed_active_tenant(
            session_factory, crypto, subdomain="beta", company_name="Beta", company_domain="beta-corp.com"
        )

        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)

        await _seed_job(resolver, tenant_a.tenant_id, title="Acme Open Job")
        await _seed_job(resolver, tenant_a.tenant_id, title="Acme Closed Job", status="CLOSED")
        await _seed_job(resolver, tenant_b.tenant_id, title="Beta Open Job")

        service = PublicBoardService(tenant_resolver=resolver, max_tenants_scanned=200)
        jobs = await service.list_open_jobs()

        titles = {j["title"] for j in jobs}
        assert titles == {"Acme Open Job", "Beta Open Job"}

        by_title = {j["title"]: j for j in jobs}
        assert by_title["Acme Open Job"]["tenant_id"] == tenant_a.tenant_id
        assert by_title["Acme Open Job"]["tenant_subdomain"] == "acme"
        assert by_title["Beta Open Job"]["company_name"] == "Beta"

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_list_open_jobs_empty_when_no_tenants():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)

        service = PublicBoardService(tenant_resolver=resolver, max_tenants_scanned=200)
        jobs = await service.list_open_jobs()
        assert jobs == []

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_max_tenants_scanned_is_respected():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        tenant_a = await seed_active_tenant(session_factory, crypto, subdomain="acme", company_domain="acme-corp.com")
        tenant_b = await seed_active_tenant(session_factory, crypto, subdomain="beta", company_domain="beta-corp.com")
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)

        await _seed_job(resolver, tenant_a.tenant_id, title="Job A")
        await _seed_job(resolver, tenant_b.tenant_id, title="Job B")

        service = PublicBoardService(tenant_resolver=resolver, max_tenants_scanned=1)
        jobs = await service.list_open_jobs()
        assert len(jobs) == 1  # only one tenant scanned

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())