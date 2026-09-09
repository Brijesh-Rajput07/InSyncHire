# LOCATION: services/job_service/tests/test_routes_integration.py

"""
Integration test: drives the REAL job_service.main.app through httpx's
ASGI transport -- a recruiter posts a job, a candidate discovers it via
the public board, applies (using the X-Tenant-Id header the public
board response supplies), and the recruiter advances the application.
Also proves role/candidate enforcement at the actual FastAPI dependency
layer (not just the service layer, covered separately).
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
from auth_tokens import TokenService, generate_rsa_keypair_pem
from cryptography.fernet import Fernet
from job_service import auth_dependency
from job_service.dependencies import (
    get_application_service,
    get_job_posting_service,
    get_public_board_service,
    get_tenant_resolver,
)
from job_service.main import app
from job_service.models import GlobalBase
from job_service.repositories import GlobalUserRepository
from job_service.services import ApplicationService, JobPostingService, PublicBoardService
from job_service.tenant_db import TenantResolver
from shared.db import make_session_factory

from .conftest import build_fake_redis, build_global_test_engine, build_test_crypto, build_test_fingerprint, seed_active_tenant, seed_global_user


def _build_token_service(redis) -> TokenService:
    private_pem, public_pem = generate_rsa_keypair_pem()
    return TokenService(
        private_key_pem=private_pem, public_key_pem=public_pem,
        fernet_key=Fernet.generate_key().decode(), redis=redis,
    )


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


def test_full_job_posting_and_application_flow():
    async def _run():
        global_engine = build_global_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_session_factory = make_session_factory(global_engine)
        crypto = build_test_crypto()

        tenant = await seed_active_tenant(global_session_factory, crypto, subdomain="acme", company_name="Acme Corp")
        resolver = TenantResolver(global_session_factory=global_session_factory, crypto=crypto)

        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        global_user_repo = GlobalUserRepository(global_session_factory)
        auth_dependency.configure(token_service, global_user_repo)

        publisher = FakePublisher()
        app.dependency_overrides[get_tenant_resolver] = lambda: resolver
        app.dependency_overrides[get_job_posting_service] = lambda: JobPostingService(publish=publisher.publish)
        app.dependency_overrides[get_application_service] = lambda: ApplicationService(publish=publisher.publish)
        app.dependency_overrides[get_public_board_service] = lambda: PublicBoardService(
            tenant_resolver=resolver, max_tenants_scanned=200
        )

        try:
            org_id = uuid.uuid4()
            recruiter_id = uuid.uuid4()
            recruiter_tokens = await token_service.issue_token_pair(
                user_id=recruiter_id, tenant_id=tenant.tenant_id, org_id=org_id, role="recruiter",
                fingerprint=build_test_fingerprint(),
            )

            candidate_id = uuid.uuid4()
            await seed_global_user(global_session_factory, candidate_id, "candidate")
            candidate_tokens = await token_service.issue_token_pair(
                user_id=candidate_id, tenant_id=None, org_id=None, role=None,
                fingerprint=build_test_fingerprint(),
            )

            transport = httpx.ASGITransport(app=app)

            # 1. Recruiter posts a job
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": recruiter_tokens.access_token},
            ) as recruiter_client:
                r1 = await recruiter_client.post(
                    "/jobs",
                    json={
                        "title": "Backend Engineer", "description": "Build things",
                        "skills_tags": ["python", "fastapi"], "location": "Remote",
                    },
                )
                assert r1.status_code == 201, r1.text
                job_id = r1.json()["job_id"]

            # 2. Public board shows it (no auth)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as public_client:
                r2 = await public_client.get("/public/jobs")
                assert r2.status_code == 200, r2.text
                listings = r2.json()
                assert len(listings) == 1
                assert listings[0]["job_id"] == job_id
                assert listings[0]["tenant_id"] == str(tenant.tenant_id)
                assert listings[0]["company_name"] == "Acme Corp"

            # 3. Candidate applies, using the tenant_id from the public listing
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": candidate_tokens.access_token},
            ) as candidate_client:
                r3 = await candidate_client.post(
                    f"/jobs/{job_id}/apply",
                    json={"cover_note": "I would love this role"},
                    headers={"x-tenant-id": str(tenant.tenant_id)},
                )
                assert r3.status_code == 201, r3.text
                application_id = r3.json()["application_id"]
                assert r3.json()["status"] == "APPLIED"

                # Duplicate apply rejected
                r3b = await candidate_client.post(
                    f"/jobs/{job_id}/apply", json={}, headers={"x-tenant-id": str(tenant.tenant_id)},
                )
                assert r3b.status_code == 409, r3b.text

                # my-application works
                r3c = await candidate_client.get(
                    f"/jobs/{job_id}/my-application", headers={"x-tenant-id": str(tenant.tenant_id)}
                )
                assert r3c.status_code == 200
                assert r3c.json()["application_id"] == application_id

            # 4. Recruiter sees the applicant and advances them
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": recruiter_tokens.access_token},
            ) as recruiter_client:
                r4 = await recruiter_client.get(f"/jobs/{job_id}/applicants")
                assert r4.status_code == 200
                assert len(r4.json()) == 1

                r5 = await recruiter_client.post(f"/applications/{application_id}/advance")
                assert r5.status_code == 200, r5.text
                assert r5.json()["status"] == "ADVANCED"

        finally:
            app.dependency_overrides.clear()
            await resolver.dispose_all()
            await global_engine.dispose()

    asyncio.run(_run())


def test_apply_without_tenant_header_returns_400():
    async def _run():
        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        global_engine = build_global_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_session_factory = make_session_factory(global_engine)
        global_user_repo = GlobalUserRepository(global_session_factory)
        auth_dependency.configure(token_service, global_user_repo)

        try:
            candidate_id = uuid.uuid4()
            await seed_global_user(global_session_factory, candidate_id, "candidate")
            candidate_tokens = await token_service.issue_token_pair(
                user_id=candidate_id, tenant_id=None, org_id=None, role=None,
                fingerprint=build_test_fingerprint(),
            )

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": candidate_tokens.access_token},
            ) as client:
                r = await client.post(f"/jobs/{uuid.uuid4()}/apply", json={})
                assert r.status_code == 400
        finally:
            await global_engine.dispose()

    asyncio.run(_run())


def test_recruiter_role_required_to_post_job():
    async def _run():
        global_engine = build_global_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_session_factory = make_session_factory(global_engine)
        crypto = build_test_crypto()
        tenant = await seed_active_tenant(global_session_factory, crypto, subdomain="acme")
        resolver = TenantResolver(global_session_factory=global_session_factory, crypto=crypto)

        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        global_user_repo = GlobalUserRepository(global_session_factory)
        auth_dependency.configure(token_service, global_user_repo)

        app.dependency_overrides[get_tenant_resolver] = lambda: resolver

        try:
            observer_id = uuid.uuid4()
            observer_tokens = await token_service.issue_token_pair(
                user_id=observer_id, tenant_id=tenant.tenant_id, org_id=uuid.uuid4(), role="observer",
                fingerprint=build_test_fingerprint(),
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": observer_tokens.access_token},
            ) as client:
                r = await client.post("/jobs", json={"title": "x", "description": "y"})
                assert r.status_code == 403, r.text
        finally:
            app.dependency_overrides.clear()
            await resolver.dispose_all()
            await global_engine.dispose()

    asyncio.run(_run())


def test_health():
    async def _run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/health")
            assert r.status_code == 200
            assert r.json()["service"] == "job_service"

    asyncio.run(_run())