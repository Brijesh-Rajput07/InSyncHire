# LOCATION: services/notification_service/notification_service/dependencies.py

"""Dependency wiring for the headless Notification Service -- no
FastAPI DI here (there are no HTTP routes), just plain factory
functions `main.py` calls at startup, same shape as
`migration_service`'s wiring."""

from __future__ import annotations

from shared.db import make_engine, make_session_factory
from shared.db.crypto import ConnectionStringCrypto

from .config import get_config
from .email import build_email_sender
from .repositories import GlobalTenantRepository, GlobalUserRepository
from .services import NotificationDispatchService
from .tenant_db import TenantResolver

_config = get_config()

_global_engine = make_engine(_config.global_db_dsn)
_global_session_factory = make_session_factory(_global_engine)

_global_tenant_repository = GlobalTenantRepository(_global_session_factory)
_global_user_repository = GlobalUserRepository(_global_session_factory)

_tenant_resolver: TenantResolver | None = None
_fallback_connection_string_key: str | None = None


def _get_connection_string_key() -> str:
    """Dev/test fallback ONLY -- same precedent as every other service's
    `_get_connection_string_key()`/`_get_fernet_key()`. A real deployment
    always sets `CONNECTION_STRING_ENCRYPTION_KEY` (must match Migration
    Service's value exactly)."""
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


def get_global_tenant_repository() -> GlobalTenantRepository:
    return _global_tenant_repository


def get_global_user_repository() -> GlobalUserRepository:
    return _global_user_repository


def get_notification_dispatch_service() -> NotificationDispatchService:
    email_sender = build_email_sender(
        provider=_config.email_provider,
        sendgrid_api_key=_config.sendgrid_api_key,
        from_address=_config.email_from_address,
    )
    return NotificationDispatchService(
        email_sender=email_sender,
        global_tenant_repository=_global_tenant_repository,
        global_user_repository=_global_user_repository,
        tenant_resolver=get_tenant_resolver(),
    )