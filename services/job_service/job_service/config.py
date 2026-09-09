# LOCATION: services/job_service/job_service/config.py

"""
Env-based configuration for the Job Service (M5). All secrets from
environment variables only (Section 10i).

Job Service reads insynchire_global for two purposes:
  1. Resolving a tenant's connection string (same TenantResolver
     pattern as Tenant Service, M3) for recruiter/company_admin routes.
  2. Iterating ACTIVE tenants to build the public job board (see
     services/public_board_service.py's docstring for why this is an
     interim implementation, not the Reporting Service aggregate the
     project plan specifies -- Reporting Service is M12, not yet built).
It also reads global_users (read-only) to distinguish a candidate
caller from an unselected company_user, same pattern as
user_profile_service (M4) -- see auth_dependency.py.
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
class JobServiceConfig:
    global_db_dsn: str = os.getenv(
        "GLOBAL_DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5433/insynchire_global"
    )
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

    # Interim public board cap (see public_board_service.py) -- bounds
    # how many ACTIVE tenants get queried per /public/jobs call until
    # Reporting Service (M12) replaces this with a single aggregate read.
    public_board_max_tenants_scanned: int = int(os.getenv("PUBLIC_BOARD_MAX_TENANTS_SCANNED", "200"))


_cached: JobServiceConfig | None = None


def get_config() -> JobServiceConfig:
    global _cached
    if _cached is None:
        _cached = JobServiceConfig()
    return _cached