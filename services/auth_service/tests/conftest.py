# LOCATION: services/auth_service/tests/conftest.py

"""
Shared test helpers. Same approach as migration_service's tests:
plain sync factory functions, async bodies wrapped in asyncio.run()
directly (no pytest-asyncio), fakeredis instead of real Redis, SQLite
instead of real Postgres.
"""

from __future__ import annotations

from fakeredis import aioredis as fake_aioredis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool


def build_test_engine() -> AsyncEngine:
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


def build_fake_redis():
    """A fresh, isolated in-memory fake Redis per call -- tests must
    each get their own instance so OTP/denylist state doesn't leak
    between tests."""
    return fake_aioredis.FakeRedis(decode_responses=True)
