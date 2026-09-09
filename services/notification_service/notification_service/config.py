# LOCATION: services/notification_service/notification_service/config.py

"""
Env-based configuration for the Notification Service (M7). All secrets
from environment variables only (Section 10i).

This service reads `insynchire_global.tenants` / `insynchire_global.global_users`
(read-only -- resolving connection strings and recipient emails, the
same read pattern every other service that needs cross-database context
already uses, e.g. tenant_service/job_service reading `tenants`) and, to
resolve which recruiters/company_admins to notify for
`application.submitted`/`scorecard.generated`, connects to the relevant
tenant DB and reads `tenant_user_memberships` (also read-only). It never
writes to any database it doesn't own -- and it doesn't own any
database at all; its only "write" is sending an email. See README.md's
"DB ownership" section for why `users_db.user_notifications` writes
live in `user_profile_service` instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationServiceConfig:
    global_db_dsn: str = os.getenv(
        "GLOBAL_DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5433/insynchire_global"
    )
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    kafka_consumer_group: str = os.getenv("NOTIFICATION_SERVICE_KAFKA_GROUP", "notification_service")

    # MUST match Migration Service's value exactly -- see module docstring.
    connection_string_encryption_key: str | None = os.getenv("CONNECTION_STRING_ENCRYPTION_KEY")

    email_provider: str = os.getenv("EMAIL_PROVIDER", "console")
    # "console" (default, DEV/TEST ONLY) | "sendgrid"
    sendgrid_api_key: str | None = os.getenv("SENDGRID_API_KEY") or None
    email_from_address: str = os.getenv("EMAIL_FROM_ADDRESS", "notifications@insynchire.example")


_cached: NotificationServiceConfig | None = None


def get_config() -> NotificationServiceConfig:
    global _cached
    if _cached is None:
        _cached = NotificationServiceConfig()
    return _cached