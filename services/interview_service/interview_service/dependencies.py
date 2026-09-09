# LOCATION: services/interview_service/interview_service/dependencies.py

"""FastAPI dependency providers (Section 6), same pattern as
job_service/dependencies.py."""

from __future__ import annotations

from insynchire_events import EventProducer
from redis.asyncio import Redis, from_url

from auth_tokens import TokenService, generate_rsa_keypair_pem
from shared.db import make_engine, make_session_factory
from shared.db.crypto import ConnectionStringCrypto

from . import auth_dependency
from .broadcaster import InProcessBroadcaster
from .config import get_config
from .connection_manager import SessionConnectionRegistry
from .crypto import RoomTokenCrypto
from .repositories import GlobalTenantRepository, GlobalUserRepository
from .services import JoinService, SchedulingService
from .tenant_db import TenantResolver
from .ws_tokens import WSConnectTokenService

_config = get_config()

_global_engine = make_engine(_config.global_db_dsn)
_global_session_factory = make_session_factory(_global_engine)

# This service verifies tokens but issues none of its own, and has no
# Redis-backed state of its own (no OTP, no invite tokens) -- Redis is
# only needed here because auth_tokens.TokenService's denylist checks
# require a Redis client, same as job_service.
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
    """Dev/test fallback ONLY -- same precedent as every other service's
    `_get_connection_string_key()`. A real deployment always sets
    `CONNECTION_STRING_ENCRYPTION_KEY` (must match Migration Service's
    value exactly)."""
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


_fallback_room_token_key: str | None = None


def _get_room_token_crypto() -> RoomTokenCrypto:
    global _fallback_room_token_key
    if _config.room_token_encryption_key:
        return RoomTokenCrypto(key=_config.room_token_encryption_key)
    if _fallback_room_token_key is None:
        from cryptography.fernet import Fernet

        _fallback_room_token_key = Fernet.generate_key().decode()
    return RoomTokenCrypto(key=_fallback_room_token_key)


async def get_publish():
    if _event_producer._producer is None:  # noqa: SLF001 - lazy start
        await _event_producer.start()
    return _event_producer.publish


def get_token_service() -> TokenService:
    return _token_service


def get_global_tenant_repository() -> GlobalTenantRepository:
    return _global_tenant_repository


def get_scheduling_service() -> SchedulingService:
    return SchedulingService(publish=_event_producer.publish, room_token_crypto=_get_room_token_crypto())


# --- M9: WebSocket gateway singletons -----------------------------------
# One registry/broadcaster for the whole process (every WebSocket
# connection shares them) -- NOT per-request, unlike the DB-session-
# scoped dependencies above. See connection_manager.py/broadcaster.py.
_ws_registry = SessionConnectionRegistry()
_ws_broadcaster = InProcessBroadcaster(_ws_registry)

_fallback_ws_token_ttl_seconds = 300


def _get_ws_connect_token_service() -> WSConnectTokenService:
    return WSConnectTokenService(
        crypto=_get_room_token_crypto(),
        ttl_seconds=_config.ws_connect_token_ttl_seconds,
    )


def get_ws_registry() -> SessionConnectionRegistry:
    return _ws_registry


def get_ws_broadcaster() -> InProcessBroadcaster:
    return _ws_broadcaster


def get_ws_connect_token_service() -> WSConnectTokenService:
    return _get_ws_connect_token_service()


def get_join_service() -> JoinService:
    return JoinService(
        room_token_crypto=_get_room_token_crypto(),
        ws_token_service=_get_ws_connect_token_service(),
    )