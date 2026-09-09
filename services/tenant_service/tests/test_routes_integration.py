# LOCATION: services/tenant_service/tests/test_routes_integration.py

"""
Integration test: drives the REAL tenant_service.main.app through
httpx's ASGI transport, proving the routes + dependency wiring work end
to end -- a company_admin invites a recruiter, the recruiter accepts,
gets a tenant-scoped session, and is verified as a real member.

The plaintext invite token is captured via `caplog` with
`debug_log=True` on InviteService -- the same dev-testing pattern as
Auth Service's OTP_DEBUG_LOG_ENABLED (see LOCAL_APP_SETUP.md), applied
here to prove the FULL round trip through real HTTP, not just the
service layer in isolation (that's covered separately in
test_invite_service.py / test_invite_acceptance_service.py).
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid

import httpx
from auth_tokens import TokenService, generate_rsa_keypair_pem
from cryptography.fernet import Fernet
from shared.db import make_session_factory
from tenant_service import auth_dependency
from tenant_service.dependencies import (
    get_invite_acceptance_service,
    get_invite_service,
    get_tenant_resolver,
    get_tenant_selection_service,
    get_token_service,
)
from tenant_service.main import app
from tenant_service.models import GlobalBase
from tenant_service.repositories import MembershipRepository, OrganizationRepository
from tenant_service.services import InviteAcceptanceService, InviteService, TenantSelectionService
from tenant_service.tenant_db import TenantResolver

from .conftest import build_fake_redis, build_global_test_engine, build_test_crypto, build_test_fingerprint, seed_active_tenant


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


def test_invite_and_accept_end_to_end(caplog):
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        company_admin_id = uuid.uuid4()
        tenant = await seed_active_tenant(
            session_factory, crypto, subdomain="acme", company_domain="acme-corp.com",
            created_by_user_id=company_admin_id,
        )

        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)

        # Bootstrap: normally done by TenantProvisioningConsumerService
        # consuming tenant.created -- done directly here since this
        # test is only exercising the invite/accept/select HTTP routes.
        session, _ = await resolver.get_session_for_tenant_id(tenant.tenant_id)
        org = await OrganizationRepository(session).create(tenant_id=tenant.tenant_id, name=tenant.company_name)
        await MembershipRepository(session).create(
            user_id=company_admin_id, tenant_id=tenant.tenant_id, org_id=org.org_id, role="company_admin"
        )
        await session.commit()
        await session.close()

        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        publisher = FakePublisher()

        auth_dependency.configure(token_service)

        app.dependency_overrides[get_tenant_resolver] = lambda: resolver
        app.dependency_overrides[get_token_service] = lambda: token_service
        app.dependency_overrides[get_invite_service] = lambda: InviteService(
            ttl_seconds=604800, publish=publisher.publish, debug_log=True
        )
        app.dependency_overrides[get_invite_acceptance_service] = lambda: InviteAcceptanceService()
        app.dependency_overrides[get_tenant_selection_service] = lambda: TenantSelectionService(
            tenant_resolver=resolver, token_service=token_service
        )

        try:
            admin_tokens = await token_service.issue_token_pair(
                user_id=company_admin_id, tenant_id=tenant.tenant_id, org_id=org.org_id,
                role="company_admin", fingerprint=build_test_fingerprint(),
            )

            transport = httpx.ASGITransport(app=app)

            with caplog.at_level(logging.INFO, logger="tenant_service.invite"):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test",
                    cookies={"insynchire_access": admin_tokens.access_token},
                ) as admin_client:
                    r1 = await admin_client.post(
                        "/tenant/invites", json={"email": "newhire@acme-corp.com", "role": "recruiter"}
                    )
                    assert r1.status_code == 201, r1.text

            match = re.search(r"invite token for .*: (\S+)$", caplog.text, re.MULTILINE)
            assert match is not None, f"could not find debug-logged invite token in: {caplog.text}"
            invite_token = match.group(1)

            # A non-admin (recruiter, not yet a member) must be rejected
            # from creating invites -- role check enforced before any
            # membership exists for them.
            outsider_id = uuid.uuid4()
            outsider_tokens = await token_service.issue_token_pair(
                user_id=outsider_id, tenant_id=None, org_id=None, role=None, fingerprint=build_test_fingerprint()
            )
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": outsider_tokens.access_token},
            ) as outsider_client:
                # Not yet a member -- selecting the tenant must fail
                r2 = await outsider_client.post("/tenant/select", json={"subdomain": "acme"})
                assert r2.status_code == 403, r2.text

                # Accept the invite using this same brand-new user
                r3 = await outsider_client.post(
                    "/tenant/invites/accept",
                    json={"invite_token": invite_token},
                    headers={"x-tenant-subdomain": "acme"},
                )
                assert r3.status_code == 200, r3.text
                assert r3.json()["role"] == "recruiter"
                assert "insynchire_access" in r3.cookies

            # Verify: a real membership row now exists for this user
            verify_session, _ = await resolver.get_session_for_tenant_id(tenant.tenant_id)
            membership = await MembershipRepository(verify_session).get_by_user_and_tenant(
                outsider_id, tenant.tenant_id
            )
            assert membership is not None
            assert membership.role == "recruiter"
            await verify_session.close()

            # And now selecting the tenant (a redundant but valid path)
            # succeeds, since a real membership exists
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": outsider_tokens.access_token},
            ) as now_member_client:
                r4 = await now_member_client.post("/tenant/select", json={"subdomain": "acme"})
                assert r4.status_code == 200, r4.text
                assert r4.json()["role"] == "recruiter"

        finally:
            app.dependency_overrides.clear()
            await resolver.dispose_all()
            await engine.dispose()

    asyncio.run(_run())


def test_expired_invite_returns_410_gone():
    """FIX-M3: expired invites return 410 Gone (not 400), per Section 4's
    exact wording: "return 410 Gone, prompt company_admin to re-send invite"."""

    async def _run():
        import hashlib
        from datetime import datetime, timedelta, timezone

        from tenant_service.repositories import InviteRepository

        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        tenant = await seed_active_tenant(session_factory, crypto, subdomain="acme")
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)

        session, _ = await resolver.get_session_for_tenant_id(tenant.tenant_id)
        await OrganizationRepository(session).create(tenant_id=tenant.tenant_id, name=tenant.company_name)
        await InviteRepository(session).create(
            tenant_id=tenant.tenant_id,
            email="latecomer@acme-corp.com",
            role="recruiter",
            invited_by=uuid.uuid4(),
            token_hash=hashlib.sha256(b"expired-token-xyz").hexdigest(),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        await session.commit()
        await session.close()

        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        auth_dependency.configure(token_service)

        app.dependency_overrides[get_tenant_resolver] = lambda: resolver
        app.dependency_overrides[get_invite_acceptance_service] = lambda: InviteAcceptanceService()

        try:
            candidate_tokens = await token_service.issue_token_pair(
                user_id=uuid.uuid4(), tenant_id=None, org_id=None, role=None,
                fingerprint=build_test_fingerprint(),
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
                cookies={"insynchire_access": candidate_tokens.access_token},
            ) as client:
                r = await client.post(
                    "/tenant/invites/accept",
                    json={"invite_token": "expired-token-xyz"},
                    headers={"x-tenant-subdomain": "acme"},
                )
                assert r.status_code == 410, r.text
                assert "resend" in r.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()
            await resolver.dispose_all()
            await engine.dispose()

    asyncio.run(_run())
