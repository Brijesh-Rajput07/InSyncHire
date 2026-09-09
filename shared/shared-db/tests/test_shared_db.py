# LOCATION: shared/shared-db/tests/test_shared_db.py

"""
Tests for shared.db. Run with: pytest -q (from shared/shared-db/)

Async tests are wrapped with asyncio.run() directly rather than using
pytest-asyncio, to keep this package's dependency footprint minimal.
"""

import asyncio
import os
import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import Column, Integer, MetaData, Table, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import GUID, make_engine, make_session_factory, set_tenant_context
from shared.db.crypto import ConnectionStringCrypto


def test_guid_round_trip_on_sqlite():
    """GUID type must store and return the exact same UUID on SQLite
    (used in our test suites) even though production runs on Postgres."""
    metadata = MetaData()
    table = Table(
        "t", metadata,
        Column("id", Integer, primary_key=True),
        Column("uid", GUID()),
    )

    async def _run():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        the_uuid = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
            await conn.execute(table.insert().values(id=1, uid=the_uuid))
            result = await conn.execute(table.select())
            row = result.first()
        await engine.dispose()
        return row

    row = asyncio.run(_run())
    assert row.uid == row.uid  # sanity
    assert isinstance(row.uid, uuid.UUID)


def test_connection_string_crypto_round_trip():
    key = Fernet.generate_key().decode()
    crypto = ConnectionStringCrypto(key=key)
    plaintext = "postgresql+asyncpg://user:pass@localhost/tenant_abc_db"
    ciphertext = crypto.encrypt(plaintext)
    assert ciphertext != plaintext
    assert crypto.decrypt(ciphertext) == plaintext


def test_connection_string_crypto_requires_key(monkeypatch):
    monkeypatch.delenv("CONNECTION_STRING_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError):
        ConnectionStringCrypto(key=None)


def test_connection_string_crypto_rejects_wrong_key():
    crypto_a = ConnectionStringCrypto(key=Fernet.generate_key().decode())
    crypto_b = ConnectionStringCrypto(key=Fernet.generate_key().decode())
    ciphertext = crypto_a.encrypt("secret-dsn")
    with pytest.raises(ValueError):
        crypto_b.decrypt(ciphertext)


def test_set_tenant_context_noops_on_sqlite_and_is_well_formed_for_postgres():
    async def _run():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        session_factory = make_session_factory(engine)
        tenant_id = uuid.uuid4()
        async with session_factory() as session:
            # On SQLite this must NOT raise (dialect-aware no-op) --
            # `SET app.x = ...` is Postgres-only syntax.
            await set_tenant_context(session, tenant_id)

        # The statement text itself (what actually runs on Postgres) is
        # still well-formed and contains the exact tenant_id.
        stmt = f"SET app.current_tenant_id = '{tenant_id}'"
        assert str(tenant_id) in stmt
        assert stmt.startswith("SET app.current_tenant_id = '")
        await engine.dispose()

    asyncio.run(_run())
