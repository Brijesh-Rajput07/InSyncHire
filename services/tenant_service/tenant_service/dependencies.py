# LOCATION: services/tenant_service/tenant_service/dependencies.py

"""FastAPI dependency providers, same pattern as auth_service/dependencies.py."""

from __future__ import annotations

from insynchire_events import EventProducer
from redis.asyncio import Redis, from_url

from auth_tokens import TokenService, generate_rsa_keypair_pem
from shared.db import make_engine, make_session_factory
from shared.db.crypto import ConnectionStringCrypto

from . import auth_dependency
from .config import get_config
from .repositories import GlobalTenantRepository, GlobalUserRepository
from .services import (
    InviteAcceptanceService,
    InviteService,
    TenantProvisioningConsumerService,
    TenantSelectionService,
)
from .tenant_db import TenantResolver

_config = get_config()

_global_engine = make_engine(_config.global_db_dsn)
_global_session_factory = make_session_factory(_global_engine)

_redis: Redis = from_url(_config.redis_url, decode_responses=True)

_event_producer = EventProducer()

# MUST match Auth Service's keys exactly -- see shared/auth-tokens/README.md.
# Falls back to an ephemeral keypair for local dev convenience ONLY; if
# this service falls back while Auth Service uses real configured keys
# (or vice versa), tokens issued by one service will fail verification
# in the other.
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
    access_ttl_seconds=_config.access_token_ttl_seconds,
    refresh_ttl_seconds=_config.refresh_token_ttl_seconds,
)
auth_dependency.configure(_token_service)

_global_tenant_repository = GlobalTenantRepository(_global_session_factory)
_global_user_repository = GlobalUserRepository(_global_session_factory)

_tenant_resolver: TenantResolver | None = None


def get_tenant_resolver() -> TenantResolver:
    """Lazily built: MUST match Migration Service's
    CONNECTION_STRING_ENCRYPTION_KEY exactly, so raises clearly at
    first use (not at import time) if it's missing."""
    global _tenant_resolver
    if _tenant_resolver is None:
        if not _config.connection_string_encryption_key:
            raise RuntimeError(
                "CONNECTION_STRING_ENCRYPTION_KEY is not set -- it must match Migration "
                "Service's value exactly. See services/tenant_service/.env.example."
            )
        crypto = ConnectionStringCrypto(key=_config.connection_string_encryption_key)
        _tenant_resolver = TenantResolver(global_session_factory=_global_session_factory, crypto=crypto)
    return _tenant_resolver


def get_token_service() -> TokenService:
    return _token_service


def get_global_tenant_repository() -> GlobalTenantRepository:
    return _global_tenant_repository


async def get_publish():
    if _event_producer._producer is None:  # noqa: SLF001 - lazy start
        await _event_producer.start()
    return _event_producer.publish


def get_invite_service() -> InviteService:
    return InviteService(
        ttl_seconds=_config.invite_ttl_seconds,
        publish=_event_producer.publish,
        debug_log=_config.invite_debug_log_enabled,
    )


def get_invite_acceptance_service() -> InviteAcceptanceService:
    return InviteAcceptanceService(global_user_repository=_global_user_repository)


def get_tenant_selection_service() -> TenantSelectionService:
    return TenantSelectionService(tenant_resolver=get_tenant_resolver(), token_service=_token_service)


def get_tenant_provisioning_consumer_service() -> TenantProvisioningConsumerService:
    return TenantProvisioningConsumerService(
        tenant_resolver=get_tenant_resolver(), global_tenant_repository=_global_tenant_repository
    )
