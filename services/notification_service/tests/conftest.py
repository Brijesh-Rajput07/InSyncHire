# LOCATION: services/notification_service/tests/conftest.py

"""
Shared test helpers -- same conventions as every other service in this
repo: plain sync factory functions, async bodies wrapped in
asyncio.run() directly, real temp-file SQLite standing in for a tenant
DB (genuinely exercises the decrypt-then-connect path, same philosophy
as tenant_service's/job_service's conftest.py), in-memory SQLite for
insynchire_global.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from notification_service.models import GlobalBase, TenantBase
from shared.db.crypto import ConnectionStringCrypto


def build_global_test_engine() -> AsyncEngine:
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )


def build_test_crypto() -> ConnectionStringCrypto:
    return ConnectionStringCrypto(key=Fernet.generate_key().decode())


async def create_temp_tenant_sqlite_dsn() -> str:
    tmp_dir = tempfile.mkdtemp(prefix="insynchire_notification_test_")
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
    from notification_service.models import Tenant as GlobalTenantModel

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


async def seed_global_user(
    global_session_factory, user_id: uuid.UUID, *, email: str, full_name: str = "Test User",
    account_type: str = "candidate",
) -> None:
    from notification_service.models import GlobalUser

    async with global_session_factory() as session:
        session.add(GlobalUser(user_id=user_id, email=email, full_name=full_name, account_type=account_type))
        await session.commit()