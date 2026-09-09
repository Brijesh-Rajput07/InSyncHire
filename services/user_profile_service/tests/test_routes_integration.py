# LOCATION: services/user_profile_service/tests/test_routes_integration.py

"""
Integration test: drives the REAL user_profile_service.main.app through
httpx's ASGI transport -- a candidate authenticates, fetches their
(auto-created) profile, updates it, uploads two resumes, and selects a
primary. Also proves a company_user (role set, tenant selected) is
rejected from every /profile route, and an unauthenticated caller gets
401 -- not just the service layer in isolation (covered separately in
test_profile_service.py / test_resume_service.py).
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
from auth_tokens import TokenService, generate_rsa_keypair_pem
from cryptography.fernet import Fernet
from shared.db import make_session_factory
from user_profile_service import auth_dependency
from user_profile_service.dependencies import get_profile_service, get_resume_service
from user_profile_service.main import app
from user_profile_service.models import GlobalBase, GlobalUser, UsersDbBase
from user_profile_service.repositories import GlobalUserRepository
from user_profile_service.services import ProfileService, ResumeService

from .conftest import build_fake_redis, build_test_engine, build_test_fingerprint


def _build_token_service(redis) -> TokenService:
    private_pem, public_pem = generate_rsa_keypair_pem()
    return TokenService(
        private_key_pem=private_pem, public_key_pem=public_pem,
        fernet_key=Fernet.generate_key().decode(), redis=redis,
    )


async def _seed_global_user(session_factory, user_id: uuid.UUID, account_type: str) -> None:
    async with session_factory() as session:
        session.add(GlobalUser(user_id=user_id, account_type=account_type))
        await session.commit()


def test_candidate_full_profile_and_resume_flow():
    async def _run():
        global_engine = build_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_session_factory = make_session_factory(global_engine)

        users_engine = build_test_engine()
        async with users_engine.begin() as conn:
            await conn.run_sync(UsersDbBase.metadata.create_all)
        users_session_factory = make_session_factory(users_engine)

        candidate_id = uuid.uuid4()
        await _seed_global_user(global_session_factory, candidate_id, "candidate")

        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        global_user_repo = GlobalUserRepository(global_session_factory)
        auth_dependency.configure(token_service, global_user_repo)

        app.dependency_overrides[get_profile_service] = lambda: ProfileService(
            users_db_session_factory=users_session_factory
        )
        app.dependency_overrides[get_resume_service] = lambda: ResumeService(
            users_db_session_factory=users_session_factory
        )

        try:
            candidate_tokens = await token_service.issue_token_pair(
                user_id=candidate_id, tenant_id=None, org_id=None, role=None,
                fingerprint=build_test_fingerprint(),
            )

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": candidate_tokens.access_token},
            ) as client:
                r1 = await client.get("/profile")
                assert r1.status_code == 200, r1.text
                assert r1.json()["user_id"] == str(candidate_id)
                assert r1.json()["bio"] is None

                r2 = await client.put("/profile", json={"bio": "Full-stack dev", "skills": ["python", "react"]})
                assert r2.status_code == 200, r2.text
                assert r2.json()["bio"] == "Full-stack dev"
                assert r2.json()["skills"] == ["python", "react"]

                r3 = await client.post(
                    "/profile/resume",
                    json={"file_url": "https://files.example.com/r1.pdf", "is_primary": True},
                )
                assert r3.status_code == 201, r3.text
                resume1_id = r3.json()["resume_id"]

                r4 = await client.post(
                    "/profile/resume",
                    json={"file_url": "https://files.example.com/r2.pdf", "is_primary": False},
                )
                assert r4.status_code == 201, r4.text
                resume2_id = r4.json()["resume_id"]

                r5 = await client.get("/profile/resume")
                assert r5.status_code == 200
                assert len(r5.json()) == 2

                r6 = await client.post("/profile/resume/select-primary", json={"resume_id": resume2_id})
                assert r6.status_code == 200, r6.text
                assert r6.json()["is_primary"] is True

                r7 = await client.get("/profile/resume")
                by_id = {r["resume_id"]: r for r in r7.json()}
                assert by_id[resume2_id]["is_primary"] is True
                assert by_id[resume1_id]["is_primary"] is False

        finally:
            app.dependency_overrides.clear()
            await global_engine.dispose()
            await users_engine.dispose()

    asyncio.run(_run())


def test_company_user_rejected_from_profile_routes():
    async def _run():
        global_engine = build_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_session_factory = make_session_factory(global_engine)

        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        global_user_repo = GlobalUserRepository(global_session_factory)
        auth_dependency.configure(token_service, global_user_repo)

        try:
            company_user_id = uuid.uuid4()
            # Tenant-scoped token (role + tenant_id set) -- never a candidate.
            company_tokens = await token_service.issue_token_pair(
                user_id=company_user_id, tenant_id=uuid.uuid4(), org_id=uuid.uuid4(),
                role="recruiter", fingerprint=build_test_fingerprint(),
            )

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": company_tokens.access_token},
            ) as client:
                r = await client.get("/profile")
                assert r.status_code == 403, r.text
        finally:
            app.dependency_overrides.clear()
            await global_engine.dispose()

    asyncio.run(_run())


def test_unauthenticated_caller_gets_401():
    async def _run():
        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        global_engine = build_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_user_repo = GlobalUserRepository(make_session_factory(global_engine))
        auth_dependency.configure(token_service, global_user_repo)

        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.get("/profile")
                assert r.status_code == 401
        finally:
            await global_engine.dispose()

    asyncio.run(_run())


def test_health():
    async def _run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/health")
            assert r.status_code == 200
            assert r.json()["service"] == "user_profile_service"

    asyncio.run(_run())