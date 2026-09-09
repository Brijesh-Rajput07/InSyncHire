# LOCATION: services/interview_service/tests/test_routes_integration.py

"""
Integration test: drives the REAL interview_service.main.app through
httpx's ASGI transport -- a recruiter schedules an interview, the
assigned interviewer joins, the candidate joins (using the
X-Tenant-Id header the same way job_service's candidate apply route
established), an unassigned observer is rejected, and an
unauthenticated caller gets 401. Also proves GET /interviews/{id}
correctly restricts interviewer/observer visibility to sessions they're
assigned to.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from auth_tokens import TokenService, generate_rsa_keypair_pem
from cryptography.fernet import Fernet
from interview_service import auth_dependency
from interview_service.dependencies import get_join_service, get_scheduling_service, get_tenant_resolver
from interview_service.main import app
from interview_service.models import GlobalBase
from interview_service.repositories import GlobalUserRepository
from interview_service.services import JoinService, SchedulingService
from interview_service.tenant_db import TenantResolver
from shared.db import make_session_factory

from .conftest import build_fake_redis, build_global_test_engine, build_test_crypto, build_test_fingerprint, build_test_room_token_crypto, build_test_ws_token_service, seed_active_tenant, seed_global_user


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


def _future_time_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


def test_full_schedule_and_join_flow():
    async def _run():
        global_engine = build_global_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_session_factory = make_session_factory(global_engine)
        crypto = build_test_crypto()
        room_crypto = build_test_room_token_crypto()

        tenant = await seed_active_tenant(global_session_factory, crypto, subdomain="acme", company_name="Acme Corp")
        resolver = TenantResolver(global_session_factory=global_session_factory, crypto=crypto)

        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        global_user_repo = GlobalUserRepository(global_session_factory)
        auth_dependency.configure(token_service, global_user_repo)

        publisher = FakePublisher()
        app.dependency_overrides[get_tenant_resolver] = lambda: resolver
        app.dependency_overrides[get_scheduling_service] = lambda: SchedulingService(
            publish=publisher.publish, room_token_crypto=room_crypto
        )
        app.dependency_overrides[get_join_service] = lambda: JoinService(
            room_token_crypto=room_crypto, ws_token_service=build_test_ws_token_service(room_crypto)
        )

        try:
            org_id = uuid.uuid4()
            recruiter_id = uuid.uuid4()
            recruiter_tokens = await token_service.issue_token_pair(
                user_id=recruiter_id, tenant_id=tenant.tenant_id, org_id=org_id, role="recruiter",
                fingerprint=build_test_fingerprint(),
            )

            assigned_interviewer_id = uuid.uuid4()
            interviewer_tokens = await token_service.issue_token_pair(
                user_id=assigned_interviewer_id, tenant_id=tenant.tenant_id, org_id=org_id, role="interviewer",
                fingerprint=build_test_fingerprint(),
            )

            unassigned_observer_id = uuid.uuid4()
            observer_tokens = await token_service.issue_token_pair(
                user_id=unassigned_observer_id, tenant_id=tenant.tenant_id, org_id=org_id, role="observer",
                fingerprint=build_test_fingerprint(),
            )

            candidate_id = uuid.uuid4()
            await seed_global_user(global_session_factory, candidate_id, "candidate")
            candidate_tokens = await token_service.issue_token_pair(
                user_id=candidate_id, tenant_id=None, org_id=None, role=None,
                fingerprint=build_test_fingerprint(),
            )

            transport = httpx.ASGITransport(app=app)

            application_id = uuid.uuid4()
            job_id = uuid.uuid4()

            # 1. Recruiter schedules the interview
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": recruiter_tokens.access_token},
            ) as recruiter_client:
                r1 = await recruiter_client.post(
                    "/interviews/schedule",
                    json={
                        "job_id": str(job_id), "application_id": str(application_id),
                        "candidate_user_id": str(candidate_id),
                        "interviewer_ids": [str(assigned_interviewer_id)],
                        "observer_ids": [], "scheduled_at": _future_time_iso(),
                    },
                )
                assert r1.status_code == 201, r1.text
                session_id = r1.json()["session_id"]
                assert "room_token" not in r1.json()

            # interview.scheduled was published -- already-built M7
            # consumers (Notification Service, user_profile_service)
            # subscribe to exactly this topic.
            topics = [t for t, _ in publisher.published]
            from insynchire_events.topics import Topics
            assert Topics.INTERVIEW_SCHEDULED.value in topics

            # 2. company_admin/recruiter can view it
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": recruiter_tokens.access_token},
            ) as recruiter_client:
                r2 = await recruiter_client.get(f"/interviews/{session_id}")
                assert r2.status_code == 200, r2.text
                assert r2.json()["status"] == "SCHEDULED"

            # 3. Assigned interviewer can view AND join
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": interviewer_tokens.access_token},
            ) as interviewer_client:
                r3 = await interviewer_client.get(f"/interviews/{session_id}")
                assert r3.status_code == 200, r3.text

                r4 = await interviewer_client.post(f"/interviews/{session_id}/join")
                assert r4.status_code == 200, r4.text
                assert r4.json()["role_in_session"] == "interviewer"
                assert len(r4.json()["room_token"]) > 0

            # 4. Unassigned observer is rejected from BOTH view and join
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": observer_tokens.access_token},
            ) as observer_client:
                r5 = await observer_client.get(f"/interviews/{session_id}")
                assert r5.status_code == 403, r5.text

                r6 = await observer_client.post(f"/interviews/{session_id}/join")
                assert r6.status_code == 403, r6.text

            # 5. Candidate joins using the X-Tenant-Id header convention
            # (their token has no tenant context at all)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": candidate_tokens.access_token},
            ) as candidate_client:
                r7 = await candidate_client.post(
                    f"/interviews/{session_id}/join", headers={"x-tenant-id": str(tenant.tenant_id)}
                )
                assert r7.status_code == 200, r7.text
                assert r7.json()["role_in_session"] == "candidate"

                # Missing the header entirely -> 400, not a confusing 403/404
                r8 = await candidate_client.post(f"/interviews/{session_id}/join")
                assert r8.status_code == 400, r8.text

        finally:
            app.dependency_overrides.clear()
            await resolver.dispose_all()
            await global_engine.dispose()

    asyncio.run(_run())


def test_unauthenticated_caller_gets_401():
    async def _run():
        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        global_engine = build_global_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_user_repo = GlobalUserRepository(make_session_factory(global_engine))
        auth_dependency.configure(token_service, global_user_repo)

        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.post("/interviews/schedule", json={})
                assert r.status_code == 401
        finally:
            await global_engine.dispose()

    asyncio.run(_run())


def test_candidate_cannot_schedule_interviews():
    async def _run():
        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        global_engine = build_global_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_user_repo = GlobalUserRepository(make_session_factory(global_engine))
        auth_dependency.configure(token_service, global_user_repo)

        try:
            candidate_id = uuid.uuid4()
            candidate_tokens = await token_service.issue_token_pair(
                user_id=candidate_id, tenant_id=None, org_id=None, role=None,
                fingerprint=build_test_fingerprint(),
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": candidate_tokens.access_token},
            ) as client:
                r = await client.post(
                    "/interviews/schedule",
                    json={
                        "job_id": str(uuid.uuid4()), "application_id": str(uuid.uuid4()),
                        "candidate_user_id": str(uuid.uuid4()), "interviewer_ids": [str(uuid.uuid4())],
                        "scheduled_at": _future_time_iso(),
                    },
                )
                # No tenant context on the token at all -> 401, not 403
                # (there's no role to even be wrong about -- same
                # distinction job_service/tenant_service's auth_dependency
                # tests already draw).
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
            assert r.json()["service"] == "interview_service"

    asyncio.run(_run())