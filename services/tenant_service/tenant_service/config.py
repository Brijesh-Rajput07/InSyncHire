# LOCATION: services/tenant_service/tenant_service/config.py

"""
Env-based configuration for the Tenant Service. Notably: the RS256/
Fernet keys here MUST match Auth Service's exactly (see
shared/auth-tokens/README.md) — these are shared system secrets, not
per-service ones.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _read_file_or_env(env_var_path: str, env_var_inline: str) -> str | None:
    path = os.getenv(env_var_path)
    if path and os.path.exists(path):
        return open(path, "r").read()
    inline = os.getenv(env_var_inline)
    if inline:
        return inline.replace("\\n", "\n")
    return None


@dataclass(frozen=True)
class TenantServiceConfig:
    global_db_dsn: str = os.getenv(
        "GLOBAL_DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5433/insynchire_global"
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    kafka_consumer_group: str = os.getenv("TENANT_SERVICE_KAFKA_GROUP", "tenant_service")

    # MUST match Auth Service's values exactly.
    jwt_private_key_pem: str | None = field(
        default_factory=lambda: _read_file_or_env("JWT_PRIVATE_KEY_PATH", "JWT_PRIVATE_KEY_PEM")
    )
    jwt_public_key_pem: str | None = field(
        default_factory=lambda: _read_file_or_env("JWT_PUBLIC_KEY_PATH", "JWT_PUBLIC_KEY_PEM")
    )
    token_payload_encryption_key: str | None = os.getenv("TOKEN_PAYLOAD_ENCRYPTION_KEY")

    # MUST match Migration Service's value exactly -- this is what lets
    # Tenant Service decrypt the tenant connection strings Migration
    # Service encrypted and stored.
    connection_string_encryption_key: str | None = os.getenv("CONNECTION_STRING_ENCRYPTION_KEY")

    access_token_ttl_seconds: int = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", str(15 * 60)))
    refresh_token_ttl_seconds: int = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", str(7 * 24 * 60 * 60)))
    cookie_domain: str | None = os.getenv("COOKIE_DOMAIN") or None
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "true").lower() == "true"

    invite_ttl_seconds: int = int(os.getenv("INVITE_TTL_SECONDS", str(7 * 24 * 60 * 60)))
    invite_debug_log_enabled: bool = os.getenv("INVITE_DEBUG_LOG_ENABLED", "false").lower() == "true"
    """DEV/TEST ONLY -- same rationale as Auth Service's OTP_DEBUG_LOG_ENABLED:
    logs the invite link since Notification Service (M7) doesn't exist yet."""


_cached: TenantServiceConfig | None = None


def get_config() -> TenantServiceConfig:
    global _cached
    if _cached is None:
        _cached = TenantServiceConfig()
    return _cached
