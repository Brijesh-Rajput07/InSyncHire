# LOCATION: services/auth_service/tests/test_login_service.py

"""Tests for LoginService: correct credentials succeed, wrong password
and unknown email both fail identically (no email enumeration), and
inactive accounts are rejected even with correct credentials."""

import asyncio
import uuid

import pytest

from auth_service.models import GlobalBase
from auth_service.repositories import UserRepository
from auth_service.services.login_service import (
    AccountInactiveError,
    InvalidCredentialsError,
    LoginService,
)
from auth_service.services.password_service import hash_password
from auth_service.services.token_service import TokenService, generate_rsa_keypair_pem
from cryptography.fernet import Fernet
from shared.db import make_session_factory

from .conftest import build_fake_redis, build_test_engine


def _build_token_service(redis) -> TokenService:
    private_pem, public_pem = generate_rsa_keypair_pem()
    return TokenService(
        private_key_pem=private_pem, public_key_pem=public_pem,
        fernet_key=Fernet.generate_key().decode(), redis=redis,
    )


async def _seed_user(session_factory, *, email: str, password: str, is_active: bool = True):
    async with session_factory() as session:
        user = await UserRepository(session).create_user(
            user_id=uuid.uuid4(), email=email, password_hash=hash_password(password),
            full_name="Test User", account_type="candidate", is_email_verified=True,
        )
        if not is_active:
            user.is_active = False
        await session.commit()
        return user.user_id


def test_login_success():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        await _seed_user(session_factory, email="jane@example.com", password="correct-password-123")

        redis = build_fake_redis()
        service = LoginService(token_service=_build_token_service(redis))

        async with session_factory() as session:
            result = await service.login(
                session=session, email="jane@example.com", password="correct-password-123", fingerprint="fp"
            )

        assert result.user.email == "jane@example.com"
        assert result.tokens.access_token

        await engine.dispose()

    asyncio.run(_run())


def test_login_wrong_password_rejected():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        await _seed_user(session_factory, email="jane@example.com", password="correct-password-123")

        redis = build_fake_redis()
        service = LoginService(token_service=_build_token_service(redis))

        async with session_factory() as session:
            with pytest.raises(InvalidCredentialsError):
                await service.login(
                    session=session, email="jane@example.com", password="WRONG", fingerprint="fp"
                )

        await engine.dispose()

    asyncio.run(_run())


def test_login_unknown_email_rejected_with_same_error():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)

        redis = build_fake_redis()
        service = LoginService(token_service=_build_token_service(redis))

        async with session_factory() as session:
            with pytest.raises(InvalidCredentialsError):
                await service.login(
                    session=session, email="nobody@example.com", password="whatever", fingerprint="fp"
                )

        await engine.dispose()

    asyncio.run(_run())


def test_login_inactive_account_rejected():
    async def _run():
        engine = build_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        await _seed_user(
            session_factory, email="jane@example.com", password="correct-password-123", is_active=False
        )

        redis = build_fake_redis()
        service = LoginService(token_service=_build_token_service(redis))

        async with session_factory() as session:
            with pytest.raises(AccountInactiveError):
                await service.login(
                    session=session, email="jane@example.com", password="correct-password-123", fingerprint="fp"
                )

        await engine.dispose()

    asyncio.run(_run())
