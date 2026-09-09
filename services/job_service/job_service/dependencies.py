# LOCATION: services/job_service/job_service/dependencies.py

"""FastAPI dependency providers (Section 6)."""

from __future__ import annotations

from insynchire_events import EventProducer
from redis.asyncio import Redis, from_url

from auth_tokens import TokenService, generate_rsa_keypair_pem
from shared.db import make_engine, make_session_factory
from shared.db.crypto import ConnectionStringCrypto

from . import auth_dependency
from .config import get_config
from .repositories import GlobalTenantRepository, GlobalUserRepository
from .services import ApplicationService, JobPostingService, PublicBoardService
from .tenant_db import TenantResolver

_config = get_config()

_global_engine = make_engine(_config.global_db_dsn)
_global_session_factory = make_session_factory(_global_engine)

_redis: Redis = from_url(_config.redis_url, decode_responses=True)

_event_producer = EventProducer()

# MUST match Auth Service's keys exactly -- this service only VERIFIES
# tokens, it never issues its own.
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

_global_tenant_repository = GlobalTenantRepository(_global_session_factory)
_global_user_repository = GlobalUserRepository(_global_session_factory)

auth_dependency.configure(_token_service, _global_user_repository)

_tenant_resolver: TenantResolver | None = None
_fallback_connection_string_key: str | None = None


def _get_connection_string_key() -> str:
    """Dev/test fallback ONLY -- same precedent as `_get_fernet_key()`
    above. A real deployment always sets CONNECTION_STRING_ENCRYPTION_KEY
    (must match Migration Service's value exactly); falling back here
    means this process can decrypt exactly nothing Migration Service
    actually encrypted, so a misconfigured production deploy fails
    loudly the first time a tenant DB is actually resolved -- it just
    doesn't fail at dependency-injection time for routes that validate
    other things (e.g. a missing X-Tenant-Id header) before ever
    touching the resolver."""
    global _fallback_connection_string_key
    if _config.connection_string_encryption_key:
        return _config.connection_string_encryption_key
    if _fallback_connection_string_key is None:
        from cryptography.fernet import Fernet

        _fallback_connection_string_key = Fernet.generate_key().decode()
    return _fallback_connection_string_key


def get_tenant_resolver() -> TenantResolver:
    global _tenant_resolver
    if _tenant_resolver is None:
        crypto = ConnectionStringCrypto(key=_get_connection_string_key())
        _tenant_resolver = TenantResolver(global_session_factory=_global_session_factory, crypto=crypto)
    return _tenant_resolver


async def get_publish():
    if _event_producer._producer is None:  # noqa: SLF001 - lazy start
        await _event_producer.start()
    return _event_producer.publish


def get_token_service() -> TokenService:
    return _token_service


def get_global_tenant_repository() -> GlobalTenantRepository:
    return _global_tenant_repository


def get_job_posting_service() -> JobPostingService:
    return JobPostingService(publish=_event_producer.publish)


def get_application_service() -> ApplicationService:
    return ApplicationService(publish=_event_producer.publish)


def get_public_board_service() -> PublicBoardService:
    return PublicBoardService(
        tenant_resolver=get_tenant_resolver(),
        max_tenants_scanned=_config.public_board_max_tenants_scanned,
    )