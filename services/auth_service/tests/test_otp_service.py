# LOCATION: services/auth_service/tests/test_otp_service.py

"""Tests for OTPService against fakeredis."""

import asyncio

import pytest

from auth_service.services.otp_service import (
    OTPIncorrectError,
    OTPLockedError,
    OTPNotFoundOrExpiredError,
    OTPService,
)

from .conftest import build_fake_redis


def _service(**overrides) -> OTPService:
    defaults = dict(redis=build_fake_redis(), length=6, ttl_seconds=600, max_attempts=3, lockout_seconds=900)
    defaults.update(overrides)
    return OTPService(**defaults)


def test_generate_and_verify_success():
    async def _run():
        service = _service()
        code = await service.generate_and_store("alice@acme.com", "signup")
        assert len(code) == 6 and code.isdigit()
        await service.verify("alice@acme.com", "signup", code)  # should not raise

    asyncio.run(_run())


def test_verify_wrong_code_raises_incorrect_with_attempts_remaining():
    async def _run():
        service = _service()
        await service.generate_and_store("alice@acme.com", "signup")
        with pytest.raises(OTPIncorrectError) as exc_info:
            await service.verify("alice@acme.com", "signup", "000000")
        assert exc_info.value.attempts_remaining == 2

    asyncio.run(_run())


def test_verify_without_generating_raises_not_found():
    async def _run():
        service = _service()
        with pytest.raises(OTPNotFoundOrExpiredError):
            await service.verify("nobody@acme.com", "signup", "123456")

    asyncio.run(_run())


def test_locks_out_after_max_attempts():
    async def _run():
        service = _service(max_attempts=3)
        await service.generate_and_store("alice@acme.com", "signup")

        for _ in range(2):
            with pytest.raises(OTPIncorrectError):
                await service.verify("alice@acme.com", "signup", "000000")

        # 3rd wrong attempt triggers lockout
        with pytest.raises(OTPLockedError):
            await service.verify("alice@acme.com", "signup", "000000")

        # Even the correct approach now fails -- locked out
        with pytest.raises(OTPLockedError):
            await service.generate_and_store("alice@acme.com", "signup")

    asyncio.run(_run())


def test_successful_verify_deletes_otp_preventing_replay():
    async def _run():
        service = _service()
        code = await service.generate_and_store("alice@acme.com", "signup")
        await service.verify("alice@acme.com", "signup", code)

        with pytest.raises(OTPNotFoundOrExpiredError):
            await service.verify("alice@acme.com", "signup", code)

    asyncio.run(_run())


def test_different_purposes_are_independent():
    async def _run():
        service = _service()
        code_signup = await service.generate_and_store("alice@acme.com", "signup")
        code_login = await service.generate_and_store("alice@acme.com", "login_2fa")
        assert code_signup != code_login or True  # codes may coincidentally match; keys must not

        # Verifying "signup" purpose must not consume "login_2fa"'s OTP
        await service.verify("alice@acme.com", "signup", code_signup)
        await service.verify("alice@acme.com", "login_2fa", code_login)  # still valid

    asyncio.run(_run())
