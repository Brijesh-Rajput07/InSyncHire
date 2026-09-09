# LOCATION: services/interview_service/tests/conftest.py

"""
Shared test helpers -- same conventions as every other service in this
repo: plain sync factory functions, async bodies wrapped in
asyncio.run() directly, real temp-file SQLite standing in for a tenant
DB (genuinely exercises the decrypt-then-connect path, same philosophy
as tenant_service's/job_service's conftest.py), in-memory SQLite for
insynchire_global, fakeredis instead of real Redis.
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

from interview_service.crypto import RoomTokenCrypto
from interview_service.models import GlobalBase, TenantBase
from interview_service.ws_tokens import WSConnectTokenService
from shared.db.crypto import ConnectionStringCrypto


def build_test_fingerprint() -> str:
    return session_fingerprint(ip_address="127.0.0.1", user_agent=f"python-httpx/{httpx.__version__}")


def build_global_test_engine() -> AsyncEngine:
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )


def build_fake_redis():
    return fake_aioredis.FakeRedis(decode_responses=True)


def build_test_crypto() -> ConnectionStringCrypto:
    return ConnectionStringCrypto(key=Fernet.generate_key().decode())


def build_test_room_token_crypto() -> RoomTokenCrypto:
    return RoomTokenCrypto(key=Fernet.generate_key().decode())


def build_test_ws_token_service(room_token_crypto: RoomTokenCrypto | None = None) -> WSConnectTokenService:
    return WSConnectTokenService(crypto=room_token_crypto or build_test_room_token_crypto(), ttl_seconds=300)


async def create_temp_tenant_sqlite_dsn() -> str:
    tmp_dir = tempfile.mkdtemp(prefix="insynchire_interview_test_")
    db_path = Path(tmp_dir) / f"tenant_{uuid.uuid4().hex}.db"
    dsn = f"sqlite+aiosqlite:///{db_path}"

    engine = create_async_engine(dsn)
    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)
    await engine.dispose()
    return dsn


async def create_temp_global_sqlite_dsn() -> str:
    """File-based (not `:memory:`) global DB DSN -- unlike every other
    test in this suite, the M9 WebSocket gateway integration test needs
    a SECOND, independently-constructed `TenantResolver` (one used by
    the real background Uvicorn server thread, a genuinely different
    event loop than the test's own) to see the SAME seeded tenant data
    the test set up. An in-memory SQLite DB is only visible to the one
    connection/engine that created it -- a file-based DB is the only
    way two independent engines can see the same data. See
    `test_ws_gateway_integration.py`'s module docstring for the full
    "why a real server, not TestClient" explanation."""
    tmp_dir = tempfile.mkdtemp(prefix="insynchire_interview_test_global_")
    db_path = Path(tmp_dir) / f"global_{uuid.uuid4().hex}.db"
    dsn = f"sqlite+aiosqlite:///{db_path}"

    engine = create_async_engine(dsn)
    async with engine.begin() as conn:
        await conn.run_sync(GlobalBase.metadata.create_all)
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
    from interview_service.models import Tenant as GlobalTenantModel

    tenant_dsn = await create_temp_tenant_sqlite_dsn()
    tenant = GlobalTenantModel(
        tenant_id=tenant_id or uuid.uuid4(), subdomain=subdomain, company_name=company_name,
        company_domain=company_domain, db_connection_string=crypto.encrypt(tenant_dsn), status="ACTIVE",
        created_by_user_id=created_by_user_id or uuid.uuid4(),
    )
    async with global_session_factory() as session:
        session.add(tenant)
        await session.commit()
    return tenant


async def seed_global_user(global_session_factory, user_id: uuid.UUID, account_type: str) -> None:
    from interview_service.models import GlobalUser

    async with global_session_factory() as session:
        session.add(GlobalUser(user_id=user_id, account_type=account_type))
        await session.commit()