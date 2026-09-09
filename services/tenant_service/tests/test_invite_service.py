# LOCATION: services/tenant_service/tests/test_invite_service.py

import asyncio
import uuid

import pytest
from insynchire_events.topics import Topics
from shared.db import make_session_factory
from tenant_service.models import GlobalBase, Tenant
from tenant_service.services.invite_service import (
    AlreadyInvitedError,
    EmailDomainMismatchError,
    InviteService,
)
from tenant_service.tenant_db import TenantResolver

from .conftest import build_global_test_engine, build_test_crypto, seed_active_tenant


class FakePublisher:
    def __init__(self):
        self.published = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


async def _seed_and_resolve(session_factory, crypto, **kwargs):
    tenant = await seed_active_tenant(session_factory, crypto, **kwargs)
    resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
    session, tenant_row = await resolver.get_session_for_tenant_id(tenant.tenant_id)
    return session, tenant_row, resolver


def test_create_invite_success():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        session, tenant, resolver = await _seed_and_resolve(
            session_factory, crypto, company_domain="acme-corp.com"
        )

        publisher = FakePublisher()
        invited_by = uuid.uuid4()
        service = InviteService(ttl_seconds=604800, publish=publisher.publish)

        result = await service.create_invite(
            session=session, tenant=tenant, invited_by=invited_by,
            email="newhire@acme-corp.com", role="recruiter", trace_id="t1",
        )

        assert result.email == "newhire@acme-corp.com"
        assert result.role == "recruiter"
        assert len(result.invite_token) > 20  # a real random token, not empty

        topics = [t for t, _ in publisher.published]
        assert Topics.USER_INVITED.value in topics

        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_create_invite_rejects_mismatched_domain():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        session, tenant, resolver = await _seed_and_resolve(
            session_factory, crypto, company_domain="acme-corp.com"
        )

        publisher = FakePublisher()
        service = InviteService(ttl_seconds=604800, publish=publisher.publish)

        with pytest.raises(EmailDomainMismatchError):
            await service.create_invite(
                session=session, tenant=tenant, invited_by=uuid.uuid4(),
                email="someone@totally-different-company.com", role="recruiter", trace_id="t1",
            )

        # Nothing published on failure
        assert publisher.published == []

        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_create_invite_rejects_duplicate_pending_invite():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        session, tenant, resolver = await _seed_and_resolve(
            session_factory, crypto, company_domain="acme-corp.com"
        )

        publisher = FakePublisher()
        service = InviteService(ttl_seconds=604800, publish=publisher.publish)

        await service.create_invite(
            session=session, tenant=tenant, invited_by=uuid.uuid4(),
            email="newhire@acme-corp.com", role="recruiter", trace_id="t1",
        )
        with pytest.raises(AlreadyInvitedError):
            await service.create_invite(
                session=session, tenant=tenant, invited_by=uuid.uuid4(),
                email="newhire@acme-corp.com", role="interviewer", trace_id="t2",
            )

        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())
