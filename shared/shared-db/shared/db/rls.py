# LOCATION: shared/shared-db/shared/db/rls.py

"""
Row-Level Security session helper for tenant databases.

Per the project plan (Section 2, Section 10b): every tenant DB has RLS
policies enabled on every table, activated by setting
`app.current_tenant_id` at the start of the DB session. This is the
*primary* isolation mechanism — application-level `WHERE org_id = ...`
filters in the repository layer are a second, independent layer on top,
not a replacement for this.

This helper is deliberately tiny and dependency-free so every service
(Job Service, Interview Service, etc.) uses the exact same mechanism
rather than each reinventing its own `SET` statement.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Activate RLS for `tenant_id` on this session.

    Must be called once per session/transaction, before any query that
    touches an RLS-protected table. The connection routing middleware
    (Task E) calls this automatically for every authenticated request;
    headless services (like the Migration Service and Tenant Service,
    which talk to per-tenant databases directly as an administrative
    actor) call it explicitly where relevant.

    The tenant_id is always a UUID we generated ourselves server-side
    (never raw user-supplied text), so inlining it into the SET
    statement here is safe — Postgres's SET command does not support
    bind parameters for this form.

    No-ops on non-Postgres dialects (e.g. SQLite in unit tests), since
    `SET app.x = ...` is Postgres-specific syntax that would otherwise
    fail every test that exercises tenant-scoped repository code
    against SQLite. RLS itself is a Postgres-only feature — SQLite
    tests are verifying repository/business logic, not RLS enforcement,
    which can only be verified against real Postgres anyway (a missing
    policy wouldn't be caught by any application-level test regardless
    of dialect).
    """
    if session.bind is not None and session.bind.dialect.name != "postgresql":
        return
    await session.execute(text(f"SET app.current_tenant_id = '{tenant_id}'"))
