# LOCATION: services/auth_service/tests/test_routes_integration.py

"""
Integration test: exercises the REAL FastAPI app and routes (not just
the service layer) via httpx's ASGI transport, with dependency overrides
swapping in SQLite + fakeredis instead of real Postgres/Redis/Kafka.
This is what actually proves the wiring in dependencies.py + routes/*
is correct, not just the business logic underneath it.

FIX-M2: no more users_db wiring here -- Auth Service doesn't touch
users_db at all anymore (see candidate_signup_service.py).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from cryptography.fernet import Fernet

from auth_service.dependencies import (
    get_candidate_signup_service,
    get_global_session,
    get_login_service,
)
from auth_service.main import app
from auth_service.models import GlobalBase
from auth_service.services import CandidateSignupService, LoginService, OTPService
from auth_service.services.token_service import TokenService, generate_rsa_keypair_pem
from shared.db import make_session_factory

from .conftest import build_fake_redis, build_test_engine


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


def test_candidate_signup_and_login_end_to_end():
    async def _run():
        global_engine = build_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_session_factory = make_session_factory(global_engine)

        redis = build_fake_redis()
        otp_service = OTPService(redis=redis, length=6, ttl_seconds=600, max_attempts=3, lockout_seconds=900)
        private_pem, public_pem = generate_rsa_keypair_pem()
        token_service = TokenService(
            private_key_pem=private_pem, public_key_pem=public_pem,
            fernet_key=Fernet.generate_key().decode(), redis=redis,
        )
        publisher = FakePublisher()
        candidate_service = CandidateSignupService(
            redis=redis, otp_service=otp_service, token_service=token_service, publish=publisher.publish
        )
        login_service = LoginService(token_service=token_service)

        # Capture the OTP the way a real test-inbox integration would
        captured = {}
        original_generate = otp_service.generate_and_store

        async def capturing_generate(email, purpose):
            code = await original_generate(email, purpose)
            captured["code"] = code
            return code

        otp_service.generate_and_store = capturing_generate  # type: ignore[method-assign]

        async def override_global_session():
            async with global_session_factory() as session:
                yield session

        app.dependency_overrides[get_global_session] = override_global_session
        app.dependency_overrides[get_candidate_signup_service] = lambda: candidate_service
        app.dependency_overrides[get_login_service] = lambda: login_service

        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                r1 = await client.post(
                    "/signup/candidate",
                    json={"email": "jane@example.com", "full_name": "Jane Doe", "password": "super-secret-123"},
                )
                assert r1.status_code == 200, r1.text

                r2 = await client.post(
                    "/signup/candidate/verify-otp",
                    json={"email": "jane@example.com", "otp_code": captured["code"]},
                )
                assert r2.status_code == 201, r2.text
                assert "insynchire_access" in r2.cookies
                assert "insynchire_refresh" in r2.cookies

                # Now log in with the same credentials via /auth/login
                r3 = await client.post(
                    "/auth/login", json={"email": "jane@example.com", "password": "super-secret-123"}
                )
                assert r3.status_code == 200, r3.text
                assert r3.json()["account_type"] == "candidate"

                # Health check
                r4 = await client.get("/health")
                assert r4.status_code == 200
        finally:
            app.dependency_overrides.clear()
            await global_engine.dispose()

    asyncio.run(_run())
