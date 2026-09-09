# LOCATION: services/user_profile_service/user_profile_service/dependencies.py

"""FastAPI dependency providers, same pattern as every other service's
dependencies.py (Section 6)."""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from auth_tokens import TokenService, generate_rsa_keypair_pem
from shared.db import make_engine, make_session_factory

from . import auth_dependency
from .config import get_config
from .repositories import GlobalUserRepository
from .services import (
    ApplicationSubmittedConsumerService,
    NotificationRecordConsumerService,
    ProfileService,
    ResumeService,
    UserRegisteredConsumerService,
)

_config = get_config()

_global_engine = make_engine(_config.global_db_dsn)
_global_session_factory = make_session_factory(_global_engine)

_users_db_engine = make_engine(_config.users_db_dsn)
_users_db_session_factory = make_session_factory(_users_db_engine)

_redis: Redis = from_url(_config.redis_url, decode_responses=True)

# MUST match Auth Service's keys exactly -- this service only VERIFIES
# tokens, it never issues its own (no login/signup routes here).
_fallback_private_pem, _fallback_public_pem = generate_rsa_keypair_pem()
_fallback_fernet_key: str | None = None


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
)

_global_user_repository = GlobalUserRepository(_global_session_factory)

auth_dependency.configure(_token_service, _global_user_repository)

_profile_service = ProfileService(users_db_session_factory=_users_db_session_factory)
_resume_service = ResumeService(users_db_session_factory=_users_db_session_factory)
_user_registered_consumer_service = UserRegisteredConsumerService(
    users_db_session_factory=_users_db_session_factory
)
_application_submitted_consumer_service = ApplicationSubmittedConsumerService(
    users_db_session_factory=_users_db_session_factory
)
_notification_record_consumer_service = NotificationRecordConsumerService(
    users_db_session_factory=_users_db_session_factory
)


def get_token_service() -> TokenService:
    return _token_service


def get_global_user_repository() -> GlobalUserRepository:
    return _global_user_repository


def get_users_db_session_factory():
    return _users_db_session_factory


def get_profile_service() -> ProfileService:
    return _profile_service


def get_resume_service() -> ResumeService:
    return _resume_service


def get_user_registered_consumer_service() -> UserRegisteredConsumerService:
    return _user_registered_consumer_service


def get_application_submitted_consumer_service() -> ApplicationSubmittedConsumerService:
    return _application_submitted_consumer_service


def get_notification_record_consumer_service() -> NotificationRecordConsumerService:
    return _notification_record_consumer_service