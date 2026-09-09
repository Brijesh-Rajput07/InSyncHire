# LOCATION: services/auth_service/auth_service/config.py

"""
Env-based configuration for the Auth Service. All secrets from env vars
only (Section 10i). See .env.example for the full list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _read_file_or_env(env_var_path: str, env_var_inline: str) -> str | None:
    """Reads a PEM key either from a file path env var or an inline env
    var (inline is handy for containerized deploys where mounting a file
    is inconvenient — either works, file path takes precedence)."""
    path = os.getenv(env_var_path)
    if path and os.path.exists(path):
        return open(path, "r").read()
    inline = os.getenv(env_var_inline)
    if inline:
        return inline.replace("\\n", "\n")
    return None


@dataclass(frozen=True)
class AuthServiceConfig:
    # --- Databases this service talks to ---
    # FIX-M2: users_db_dsn removed -- Auth Service no longer connects to
    # users_db at all (see candidate_signup_service.py's module
    # docstring). The alembic_users_db/ migration suite still exists in
    # this folder for now and reads USERS_DB_DSN directly from the
    # environment at migration time, independent of this config class.
    global_db_dsn: str = os.getenv(
        "GLOBAL_DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5433/insynchire_global"
    )

    # --- Redis (OTP storage, token denylist) ---
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # --- OTP policy (Section 10c) ---
    otp_length: int = int(os.getenv("OTP_LENGTH", "6"))
    otp_ttl_seconds: int = int(os.getenv("OTP_TTL_SECONDS", str(10 * 60)))
    otp_max_attempts: int = int(os.getenv("OTP_MAX_ATTEMPTS", "3"))
    otp_lockout_seconds: int = int(os.getenv("OTP_LOCKOUT_SECONDS", str(15 * 60)))
    # DEV/TEST ONLY -- logs plaintext OTPs so you can test signup before
    # the Notification Service (M7) exists. Defaults to False; must be
    # explicitly enabled and should NEVER be true in a real deployment.
    otp_debug_log_enabled: bool = os.getenv("OTP_DEBUG_LOG_ENABLED", "false").lower() == "true"

    # --- Token / cookie policy (Section 10c) ---
    access_token_ttl_seconds: int = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", str(15 * 60)))
    refresh_token_ttl_seconds: int = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", str(7 * 24 * 60 * 60)))
    cookie_domain: str | None = os.getenv("COOKIE_DOMAIN") or None
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "true").lower() == "true"

    # RS256 keypair for JWT signing (PEM). In dev/test, token_service
    # falls back to generating an ephemeral keypair if these are unset.
    jwt_private_key_pem: str | None = field(
        default_factory=lambda: _read_file_or_env("JWT_PRIVATE_KEY_PATH", "JWT_PRIVATE_KEY_PEM")
    )
    jwt_public_key_pem: str | None = field(
        default_factory=lambda: _read_file_or_env("JWT_PUBLIC_KEY_PATH", "JWT_PUBLIC_KEY_PEM")
    )

    # AES-256 (Fernet) key used to encrypt the token payload before
    # signing (Section 10c: "payload encrypted before JWT signing").
    token_payload_encryption_key: str | None = os.getenv("TOKEN_PAYLOAD_ENCRYPTION_KEY")

    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")


_cached: AuthServiceConfig | None = None


def get_config() -> AuthServiceConfig:
    global _cached
    if _cached is None:
        _cached = AuthServiceConfig()
    return _cached
