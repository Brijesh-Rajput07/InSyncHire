# LOCATION: shared/shared-db/shared/db/session.py

"""
Generic async SQLAlchemy engine + session factory helpers.

Every service builds its DB access the same way: one `AsyncEngine` per
database it talks to, and one `async_sessionmaker` bound to that engine.
This module just standardizes that construction so every service doesn't
reinvent pool settings.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(dsn: str, *, echo: bool = False, pool_pre_ping: bool = True) -> AsyncEngine:
    """Create an async engine.

    `pool_pre_ping=True` avoids handing out dead connections after a DB
    restart or PgBouncer pool recycle — cheap insurance in a multi-tenant
    system where connections are pooled per-tenant (Section 10b).
    """
    return create_async_engine(dsn, echo=echo, pool_pre_ping=pool_pre_ping)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to `engine`.

    `expire_on_commit=False` so objects returned from a repository method
    remain usable (e.g. for logging/serialization) after the session's
    transaction commits, without triggering a surprise re-fetch.
    """
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
