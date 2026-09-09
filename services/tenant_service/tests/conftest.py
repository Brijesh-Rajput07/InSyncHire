# LOCATION: services/tenant_service/tests/conftest.py

"""
Shared test helpers.

For the "insynchire_global" side, same in-memory SQLite + StaticPool
pattern used elsewhere in this repo.

For the "tenant DB" side, we do something more realistic: rather than
mocking TenantResolver's decrypt-then-connect logic, we give it a REAL
(temp-file-backed, not :memory:) SQLite database to connect to, with a
REAL encrypted connection string stored on the Tenant row -- exercising
the actual decrypt + engine-build code path, not a stand-in for it.
File-backed SQLite (unlike :memory:) persists correctly across the
multiple separate connections SQLAlchemy's async engine opens, so this
works without StaticPool tricks.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import httpx
from auth_tokens import session_fingerprint
from cryptography.fernet import Fernet
from fakeredis import aioredis as fake_aioredis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from shared.db.crypto import ConnectionStringCrypto
from tenant_service.models import TenantBase


def build_test_fingerprint() -> str:
    """The exact fingerprint httpx's ASGITransport test client produces
    (FIX-M2: auth_dependency now re-validates session_fingerprint on
    every request) -- tokens issued for use through the real FastAPI
    app in tests must be issued with THIS fingerprint, or every request
    will be rejected as a fingerprint mismatch."""
    return session_fingerprint(ip_address="127.0.0.1", user_agent=f"python-httpx/{httpx.__version__}")


def build_global_test_engine() -> AsyncEngine:
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


def build_fake_redis():
    return fake_aioredis.FakeRedis(decode_responses=True)


def build_test_crypto() -> ConnectionStringCrypto:
    return ConnectionStringCrypto(key=Fernet.generate_key().decode())


async def create_temp_tenant_sqlite_dsn() -> str:
    """Creates a real, file-backed SQLite DB with the tenant tables
    already created, and returns its async DSN (unencrypted -- caller
    encrypts it with the test's ConnectionStringCrypto before storing
    on a Tenant row, matching what Migration Service does for real)."""
    tmp_dir = tempfile.mkdtemp(prefix="insynchire_tenant_test_")
    db_path = Path(tmp_dir) / f"tenant_{uuid.uuid4().hex}.db"
    dsn = f"sqlite+aiosqlite:///{db_path}"

    engine = create_async_engine(dsn)
    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)
    await engine.dispose()

    return dsn


async def seed_active_tenant(
    global_session_factory,
    crypto: ConnectionStringCrypto,
    *,
    tenant_id: uuid.UUID | None = None,
    subdomain: str = "acme",
    company_name: str = "Acme Corp",
    company_domain: str = "acme-corp.com",
    created_by_user_id: uuid.UUID | None = None,
):
    """Creates a fully-provisioned, ACTIVE tenant row in the (SQLite)
    global DB, pointing at a real temp-file tenant SQLite DB with the
    tenant tables already created -- i.e. exactly the end state
    Migration Service leaves a tenant in after M1 provisioning."""
    from tenant_service.models import Tenant as GlobalTenantModel

    tenant_dsn = await create_temp_tenant_sqlite_dsn()
    tenant = GlobalTenantModel(
        tenant_id=tenant_id or uuid.uuid4(),
        subdomain=subdomain,
        company_name=company_name,
        company_domain=company_domain,
        db_connection_string=crypto.encrypt(tenant_dsn),
        status="ACTIVE",
        created_by_user_id=created_by_user_id or uuid.uuid4(),
    )
    async with global_session_factory() as session:
        session.add(tenant)
        await session.commit()
    return tenant
