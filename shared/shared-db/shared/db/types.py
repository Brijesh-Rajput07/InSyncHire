# LOCATION: shared/shared-db/shared/db/types.py

"""
Cross-dialect UUID column type.

On Postgres (production, per the project plan — Postgres 16+ everywhere)
this stores a native `uuid` column. On SQLite (used only in this repo's
fast unit tests, never in production) it falls back to a CHAR(32) hex
string, so the exact same SQLAlchemy models can be exercised in tests
without a running Postgres instance.

Every ORM model in every service should use this `GUID` type for primary
keys / foreign keys instead of importing `postgresql.UUID` directly, so
models stay testable without Docker.
"""

from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import CHAR, TypeDecorator


class GUID(TypeDecorator):
    """Platform-independent UUID type.

    Uses Postgres's native UUID type when available, otherwise stores as
    a stringified hex CHAR(32).
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value.hex

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)
