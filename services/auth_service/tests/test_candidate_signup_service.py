# LOCATION: services/auth_service/tests/test_candidate_signup_service.py

"""
Tests for CandidateSignupService: OTP-gated completion creates the
global_users row, publishes user.registered, and returns a working
token pair (candidate is logged in immediately).

FIX-M2: this no longer touches users_db at all -- see
candidate_signup_service.py's module docstring for why the direct
profile write was removed. A future M4 service will consume
user.registered and create the profile row itself.
"""

import asyncio

import pytest

from auth_service.models import GlobalBase
from auth_service.repositories import EmailAlreadyRegisteredError
from auth_service.services.candidate_signup_service import (
    CandidateSignupService,
    PendingSignupNotFoundError,
)
from auth_service.services.otp_service import OTPService
from auth_service.services.token_service import TokenService, generate_rsa_keypair_pem
from cryptography.fernet import Fernet
from insynchire_events.topics import Topics
from shared.db import make_session_factory

from .conftest import build_fake_redis, build_test_engine


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


def _build_token_service(redis) -> TokenService:
    private_pem, public_pem = generate_rsa_keypair_pem()
    return TokenService(
        private_key_pem=private_pem, public_key_pem=public_pem,
        fernet_key=Fernet.generate_key().decode(), redis=redis,
    )


async def _capture_otp(otp_service: OTPService, email: str, purpose: str) -> str:
    original = otp_service.generate_and_store
    captured = {}

    async def capturing(e, p):
        code = await original(e, p)
        captured["code"] = code
        return code

    otp_service.generate_and_store = capturing  # type: ignore[method-assign]
    return captured  # caller reads captured["code"] after triggering initiate()


def test_full_candidate_signup_flow():
    async def _run():
        global_engine = build_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_session_factory = make_session_factory(global_engine)

        redis = build_fake_redis()
        otp_service = OTPService(redis=redis, length=6, ttl_seconds=600, max_attempts=3, lockout_seconds=900)
        token_service = _build_token_service(redis)
        publisher = FakePublisher()
        service = CandidateSignupService(
            redis=redis, otp_service=otp_service, token_service=token_service, publish=publisher.publish
        )

        captured = await _capture_otp(otp_service, "jane@example.com", "candidate_signup")
        await service.initiate(email="jane@example.com", full_name="Jane Doe", password="super-secret-123")

        async with global_session_factory() as global_session:
            result = await service.complete(
                global_session=global_session,
                email="jane@example.com",
                otp_code=captured["code"],
                fingerprint="fp-1",
                trace_id="trace-1",
            )

        assert result.email == "jane@example.com"
        assert result.tokens.access_token

        payload = await token_service.decode_and_verify(result.tokens.access_token, expected_type="access")
        assert payload.user_id == result.user_id

        topics = [t for t, _ in publisher.published]
        assert Topics.USER_REGISTERED.value in topics

        await global_engine.dispose()

    asyncio.run(_run())


def test_complete_without_pending_signup_raises():
    async def _run():
        global_engine = build_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_session_factory = make_session_factory(global_engine)

        redis = build_fake_redis()
        otp_service = OTPService(redis=redis, length=6, ttl_seconds=600, max_attempts=3, lockout_seconds=900)
        token_service = _build_token_service(redis)
        publisher = FakePublisher()
        service = CandidateSignupService(
            redis=redis, otp_service=otp_service, token_service=token_service, publish=publisher.publish
        )

        # Manually seed an OTP without ever calling initiate() (so no
        # pending-signup blob exists in Redis)
        code = await otp_service.generate_and_store("ghost@example.com", "candidate_signup")

        async with global_session_factory() as gs:
            with pytest.raises(PendingSignupNotFoundError):
                await service.complete(
                    global_session=gs, email="ghost@example.com",
                    otp_code=code, fingerprint="fp", trace_id="t1",
                )

        await global_engine.dispose()

    asyncio.run(_run())


def test_duplicate_email_rejected():
    async def _run():
        global_engine = build_test_engine()
        async with global_engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        global_session_factory = make_session_factory(global_engine)

        redis = build_fake_redis()
        otp_service = OTPService(redis=redis, length=6, ttl_seconds=600, max_attempts=3, lockout_seconds=900)
        token_service = _build_token_service(redis)
        publisher = FakePublisher()
        service = CandidateSignupService(
            redis=redis, otp_service=otp_service, token_service=token_service, publish=publisher.publish
        )

        async def signup_once():
            captured = await _capture_otp(otp_service, "dup@example.com", "candidate_signup")
            await service.initiate(email="dup@example.com", full_name="Dup User", password="super-secret-123")
            async with global_session_factory() as gs:
                return await service.complete(
                    global_session=gs, email="dup@example.com",
                    otp_code=captured["code"], fingerprint="fp", trace_id="t1",
                )

        await signup_once()
        with pytest.raises(EmailAlreadyRegisteredError):
            await signup_once()

        await global_engine.dispose()

    asyncio.run(_run())
