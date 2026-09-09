# LOCATION: services/user_profile_service/tests/conftest.py

"""Shared test helpers -- same conventions as every other service in
this repo: plain sync factory functions, async bodies wrapped in
asyncio.run() directly (no pytest-asyncio), fakeredis instead of real
Redis, in-memory SQLite instead of real Postgres."""

from __future__ import annotations

import httpx
from auth_tokens import session_fingerprint
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
    return fake_aioredis.FakeRedis(decode_responses=True)


def build_test_fingerprint() -> str:
    """The exact fingerprint httpx's ASGITransport test client produces
    -- tokens issued for use through the real FastAPI app in tests must
    be issued with THIS fingerprint (same pattern as tenant_service's
    conftest.py, FIX-M2)."""
    return session_fingerprint(ip_address="127.0.0.1", user_agent=f"python-httpx/{httpx.__version__}")