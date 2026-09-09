# LOCATION: services/migration_service/tests/conftest.py

"""
Shared test helpers.

Deliberately NOT using pytest-asyncio (see M0's dependency-conflict
lesson) -- tests instead wrap their async bodies in asyncio.run()
directly, and use this plain (synchronous) factory function to build a
fresh in-memory SQLite engine standing in for insynchire_global.

Real Postgres-only behavior (CREATE DATABASE, RLS policies, the tenant
Alembic suite) is exercised by mocking db_admin functions in
test_provisioning_service.py -- see that file for what is and isn't
covered here versus a real integration run against Postgres.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool


def build_test_engine() -> AsyncEngine:
    """In-memory SQLite engine. StaticPool + check_same_thread=False
    keeps the same DB alive across the multiple connections SQLAlchemy's
    async engine opens, instead of each connection getting a blank DB."""
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
