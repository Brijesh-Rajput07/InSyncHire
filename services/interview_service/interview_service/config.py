# LOCATION: services/interview_service/interview_service/config.py

"""
Env-based configuration for the Interview Service (M8). All secrets from
environment variables only (Section 10i).

This service reads `insynchire_global.tenants` (to resolve/decrypt a
tenant's connection string, same `TenantResolver` pattern as
`tenant_service`/`job_service`) and `insynchire_global.global_users`
(read-only -- to distinguish a candidate caller from an unselected
company_user, same pattern as `job_service`/`user_profile_service`). It
owns `interview_sessions`/`interview_participants` in each tenant DB
(Section 5, migration `0005_interview_sessions`, M8).
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
class InterviewServiceConfig:
    global_db_dsn: str = os.getenv(
        "GLOBAL_DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5433/insynchire_global"
    )
    # Only needed for auth_tokens.TokenService's Redis-backed denylist
    # check (this service verifies tokens but issues/revokes none of its
    # own) -- same requirement job_service has for the identical reason.
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    # MUST match Auth Service's values exactly -- this service only
    # VERIFIES tokens, it never issues its own.
    jwt_private_key_pem: str | None = field(
        default_factory=lambda: _read_file_or_env("JWT_PRIVATE_KEY_PATH", "JWT_PRIVATE_KEY_PEM")
    )
    jwt_public_key_pem: str | None = field(
        default_factory=lambda: _read_file_or_env("JWT_PUBLIC_KEY_PATH", "JWT_PUBLIC_KEY_PEM")
    )
    token_payload_encryption_key: str | None = os.getenv("TOKEN_PAYLOAD_ENCRYPTION_KEY")

    # MUST match Migration Service's value exactly -- lets this service
    # decrypt tenant connection strings Migration Service encrypted.
    connection_string_encryption_key: str | None = os.getenv("CONNECTION_STRING_ENCRYPTION_KEY")

    # Dedicated key for room_token encryption (Section 5) -- see
    # crypto.py's module docstring for why this is a SEPARATE key from
    # CONNECTION_STRING_ENCRYPTION_KEY rather than reusing it.
    room_token_encryption_key: str | None = os.getenv("ROOM_TOKEN_ENCRYPTION_KEY")

    # M9: how long a WebSocket connect token (ws_tokens.py) is valid
    # for after being issued at join time (Section 10e: "short-lived
    # signed token in connection URL").
    ws_connect_token_ttl_seconds: int = int(os.getenv("WS_CONNECT_TOKEN_TTL_SECONDS", "300"))


_cached: InterviewServiceConfig | None = None


def get_config() -> InterviewServiceConfig:
    global _cached
    if _cached is None:
        _cached = InterviewServiceConfig()
    return _cached