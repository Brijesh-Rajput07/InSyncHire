# LOCATION: services/auth_service/auth_service/dependencies.py

"""
FastAPI dependency providers.

Centralizing construction here (rather than in routes) keeps routes
thin per Section 6, and makes it trivial for tests to override any one
dependency (e.g. swap real Redis for fakeredis, real Postgres for
SQLite) via FastAPI's `app.dependency_overrides`.
"""

from __future__ import annotations

from typing import AsyncIterator

from insynchire_events import EventProducer
from redis.asyncio import Redis, from_url
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import make_engine, make_session_factory

from .config import get_config
from .services import (
    CandidateSignupService,
    CompanySignupService,
    DomainValidationService,
    LoginService,
    OTPService,
    TokenService,
    generate_rsa_keypair_pem,
)

_config = get_config()

_global_engine = make_engine(_config.global_db_dsn)
_global_session_factory = make_session_factory(_global_engine)

# FIX-M2: no users_db engine here anymore -- Auth Service only ever
# published user.registered; it never had legitimate business writing
# directly to users_db (that's M4's dedicated service). Removing the
# engine construction entirely (not just unused function) so Auth
# Service doesn't even hold an idle connection pool to a database it
# has no business touching.

_redis: Redis = from_url(_config.redis_url, decode_responses=True)

_event_producer = EventProducer()

# Dev/test fallback keypair -- see token_service.generate_rsa_keypair_pem's
# docstring: NEVER rely on this in production, configure real keys.
_fallback_private_pem, _fallback_public_pem = generate_rsa_keypair_pem()
_fallback_fernet_key = None  # generated lazily below only if needed


def _get_fernet_key() -> str:
    global _fallback_fernet_key
    if _config.token_payload_encryption_key:
        return _config.token_payload_encryption_key
    if _fallback_fernet_key is None:
        from cryptography.fernet import Fernet

        _fallback_fernet_key = Fernet.generate_key().decode()
    return _fallback_fernet_key


_token_service = TokenService(
    private_key_pem=_config.jwt_private_key_pem or _fallback_private_pem,
    public_key_pem=_config.jwt_public_key_pem or _fallback_public_pem,
    fernet_key=_get_fernet_key(),
    redis=_redis,
    access_ttl_seconds=_config.access_token_ttl_seconds,
    refresh_ttl_seconds=_config.refresh_token_ttl_seconds,
)

_otp_service = OTPService(
    redis=_redis,
    length=_config.otp_length,
    ttl_seconds=_config.otp_ttl_seconds,
    max_attempts=_config.otp_max_attempts,
    lockout_seconds=_config.otp_lockout_seconds,
    debug_log_otp=_config.otp_debug_log_enabled,
)

_domain_validator = DomainValidationService()


async def get_global_session() -> AsyncIterator[AsyncSession]:
    async with _global_session_factory() as session:
        yield session


def get_redis_client() -> Redis:
    return _redis


def get_token_service() -> TokenService:
    return _token_service


def get_otp_service() -> OTPService:
    return _otp_service


def get_domain_validator() -> DomainValidationService:
    return _domain_validator


async def get_publish():
    if _event_producer._producer is None:  # noqa: SLF001 - lazy start
        await _event_producer.start()
    return _event_producer.publish


def get_company_signup_service() -> CompanySignupService:
    return CompanySignupService(
        redis=_redis,
        otp_service=_otp_service,
        domain_validator=_domain_validator,
        publish=_event_producer.publish,
    )


def get_candidate_signup_service() -> CandidateSignupService:
    return CandidateSignupService(
        redis=_redis,
        otp_service=_otp_service,
        token_service=_token_service,
        publish=_event_producer.publish,
    )


def get_login_service() -> LoginService:
    return LoginService(token_service=_token_service)
