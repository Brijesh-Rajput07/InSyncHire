# LOCATION: services/user_profile_service/user_profile_service/config.py

"""
Env-based configuration for the User Profile Service (M4). All secrets
from environment variables only (Section 10i).

This service reads insynchire_global (read-only -- see
repositories/global_user_repository.py) purely to check an
authenticated caller's account_type; it never writes it. It owns
users_db as of M4.
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
class UserProfileServiceConfig:
    global_db_dsn: str = os.getenv(
        "GLOBAL_DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5433/insynchire_global"
    )
    users_db_dsn: str = os.getenv(
        "USERS_DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5433/users_db"
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    kafka_consumer_group: str = os.getenv("USER_PROFILE_SERVICE_KAFKA_GROUP", "user_profile_service")

    # MUST match Auth Service's values exactly -- this service only
    # VERIFIES tokens (via auth_tokens.TokenService.decode_and_verify),
    # it never issues its own.
    jwt_private_key_pem: str | None = field(
        default_factory=lambda: _read_file_or_env("JWT_PRIVATE_KEY_PATH", "JWT_PRIVATE_KEY_PEM")
    )
    jwt_public_key_pem: str | None = field(
        default_factory=lambda: _read_file_or_env("JWT_PUBLIC_KEY_PATH", "JWT_PUBLIC_KEY_PEM")
    )
    token_payload_encryption_key: str | None = os.getenv("TOKEN_PAYLOAD_ENCRYPTION_KEY")


_cached: UserProfileServiceConfig | None = None


def get_config() -> UserProfileServiceConfig:
    global _cached
    if _cached is None:
        _cached = UserProfileServiceConfig()
    return _cached