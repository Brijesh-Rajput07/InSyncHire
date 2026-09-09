# LOCATION: services/tenant_service/tests/test_auth_dependency.py

"""
Tests for get_current_identity + require_role, using the real FastAPI
app with a real TokenService (fakeredis-backed) -- proves the actual
cookie-reading and role-checking logic, not a mock of it.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
from auth_tokens import TokenService, generate_rsa_keypair_pem
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI

from tenant_service import auth_dependency
from tenant_service.auth_dependency import get_current_identity, require_role

from .conftest import build_fake_redis, build_test_fingerprint


def _build_token_service(redis) -> TokenService:
    private_pem, public_pem = generate_rsa_keypair_pem()
    return TokenService(
        private_key_pem=private_pem, public_key_pem=public_pem,
        fernet_key=Fernet.generate_key().decode(), redis=redis,
    )


def _build_test_app(token_service: TokenService) -> FastAPI:
    auth_dependency.configure(token_service)
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(identity=Depends(get_current_identity)):
        return {"user_id": str(identity.user_id), "role": identity.role}

    @app.get("/admin-only")
    async def admin_only(identity=Depends(require_role("company_admin"))):
        return {"ok": True}

    return app


def test_no_cookie_returns_401():
    async def _run():
        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        app = _build_test_app(token_service)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/whoami")
            assert r.status_code == 401

    asyncio.run(_run())


def test_valid_cookie_returns_identity():
    async def _run():
        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        app = _build_test_app(token_service)

        user_id = uuid.uuid4()
        tokens = await token_service.issue_token_pair(
            user_id=user_id, tenant_id=None, org_id=None, role=None, fingerprint=build_test_fingerprint()
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
            cookies={"insynchire_access": tokens.access_token},
        ) as client:
            r = await client.get("/whoami")
            assert r.status_code == 200
            assert r.json()["user_id"] == str(user_id)

    asyncio.run(_run())


def test_fingerprint_mismatch_rejected():
    """FIX-M2: a token issued for a different device/network context
    (different fingerprint) is rejected here, at the actual FastAPI
    dependency layer -- not just inside the shared TokenService."""

    async def _run():
        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        app = _build_test_app(token_service)

        tokens = await token_service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=None, org_id=None, role=None,
            fingerprint="fp-from-a-totally-different-device",
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
            cookies={"insynchire_access": tokens.access_token},
        ) as client:
            r = await client.get("/whoami")
            assert r.status_code == 401
            assert "verification failed" in r.json()["detail"].lower()

    asyncio.run(_run())


def test_require_role_rejects_wrong_role():
    async def _run():
        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        app = _build_test_app(token_service)

        tokens = await token_service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), org_id=uuid.uuid4(),
            role="recruiter", fingerprint=build_test_fingerprint(),
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
            cookies={"insynchire_access": tokens.access_token},
        ) as client:
            r = await client.get("/admin-only")
            assert r.status_code == 403

    asyncio.run(_run())


def test_require_role_rejects_no_tenant_context():
    """A candidate or a company_user who hasn't selected a tenant yet
    (role=None, tenant_id=None) must get 401, not 403 -- there's no
    role to even be wrong about."""

    async def _run():
        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        app = _build_test_app(token_service)

        tokens = await token_service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=None, org_id=None, role=None, fingerprint=build_test_fingerprint()
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
            cookies={"insynchire_access": tokens.access_token},
        ) as client:
            r = await client.get("/admin-only")
            assert r.status_code == 401
            assert "tenant" in r.json()["detail"].lower()  # the RIGHT 401, not a fingerprint mismatch

    asyncio.run(_run())


def test_require_role_accepts_matching_role():
    async def _run():
        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        app = _build_test_app(token_service)

        tokens = await token_service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), org_id=uuid.uuid4(),
            role="company_admin", fingerprint=build_test_fingerprint(),
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
            cookies={"insynchire_access": tokens.access_token},
        ) as client:
            r = await client.get("/admin-only")
            assert r.status_code == 200
            assert r.json()["ok"] is True

    asyncio.run(_run())
