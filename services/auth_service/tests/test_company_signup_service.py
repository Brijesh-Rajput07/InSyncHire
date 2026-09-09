# LOCATION: services/auth_service/tests/test_company_signup_service.py

"""
Tests for CompanySignupService: domain validation gate, OTP-gated
completion, tenant PENDING row creation, correct Kafka events published,
and duplicate-domain rejection.
"""

import asyncio

import pytest

from auth_service.models import GlobalBase
from auth_service.repositories import DomainAlreadyRegisteredError
from auth_service.services.company_signup_service import (
    CompanySignupService,
    PendingSignupNotFoundError,
)
from auth_service.services.domain_validation_service import (
    DomainValidationService,
    PublicEmailDomainError,
)
from auth_service.services.otp_service import OTPService
from insynchire_events.topics import Topics
from shared.db import make_session_factory

from .conftest import build_fake_redis, build_test_engine


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


def _build_service(publisher: FakePublisher, redis=None):
    redis = redis or build_fake_redis()
    otp_service = OTPService(redis=redis, length=6, ttl_seconds=600, max_attempts=3, lockout_seconds=900)
    domain_validator = DomainValidationService(mx_checker=lambda d: True)
    return CompanySignupService(
        redis=redis, otp_service=otp_service, domain_validator=domain_validator, publish=publisher.publish
    ), otp_service, redis


def test_initiate_rejects_public_email_domain():
    async def _run():
        publisher = FakePublisher()
        service, _, _ = _build_service(publisher)
        with pytest.raises(PublicEmailDomainError):
            await service.initiate(
                company_name="Acme", subdomain="acme", company_email="founder@gmail.com",
                full_name="Alice", password="super-secret-123",
            )

    asyncio.run(_run())


def test_full_signup_flow_success_with_captured_otp():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        publisher = FakePublisher()
        redis = build_fake_redis()
        otp_service = OTPService(redis=redis, length=6, ttl_seconds=600, max_attempts=3, lockout_seconds=900)
        domain_validator = DomainValidationService(mx_checker=lambda d: True)
        service = CompanySignupService(
            redis=redis, otp_service=otp_service, domain_validator=domain_validator, publish=publisher.publish
        )

        # Capture the code the "email" would deliver by wrapping generate_and_store
        original_generate = otp_service.generate_and_store
        captured = {}

        async def capturing_generate(email, purpose):
            code = await original_generate(email, purpose)
            captured["code"] = code
            return code

        otp_service.generate_and_store = capturing_generate  # type: ignore[method-assign]

        await service.initiate(
            company_name="Acme Corp", subdomain="acme", company_email="founder@acme-corp.com",
            full_name="Alice Founder", password="super-secret-123",
        )

        async with session_factory() as session:
            result = await service.complete(
                session=session,
                company_email="founder@acme-corp.com",
                otp_code=captured["code"],
                trace_id="trace-1",
            )

        assert result.subdomain == "acme"
        assert result.status == "PENDING"

        topics = [t for t, _ in publisher.published]
        assert Topics.USER_REGISTERED.value in topics
        assert Topics.TENANT_SIGNUP_INITIATED.value in topics

        await engine.dispose()

    asyncio.run(_run())


def test_duplicate_domain_rejected_on_complete():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        publisher = FakePublisher()
        redis = build_fake_redis()
        otp_service = OTPService(redis=redis, length=6, ttl_seconds=600, max_attempts=3, lockout_seconds=900)
        domain_validator = DomainValidationService(mx_checker=lambda d: True)
        service = CompanySignupService(
            redis=redis, otp_service=otp_service, domain_validator=domain_validator, publish=publisher.publish
        )

        async def signup_once(subdomain: str, email: str):
            captured = {}
            original_generate = otp_service.generate_and_store

            async def capturing_generate(e, purpose):
                code = await original_generate(e, purpose)
                captured["code"] = code
                return code

            otp_service.generate_and_store = capturing_generate  # type: ignore[method-assign]
            await service.initiate(
                company_name="Acme Corp", subdomain=subdomain, company_email=email,
                full_name="Alice", password="super-secret-123",
            )
            async with session_factory() as session:
                return await service.complete(
                    session=session, company_email=email,
                    otp_code=captured["code"], trace_id="trace-1",
                )

        await signup_once("acme", "founder@acme-corp.com")

        with pytest.raises(DomainAlreadyRegisteredError):
            # Different email, SAME domain -- this is what should trip
            # DomainAlreadyRegisteredError specifically, not email uniqueness.
            await signup_once("acme-two", "cofounder@acme-corp.com")

        await engine.dispose()

    asyncio.run(_run())
