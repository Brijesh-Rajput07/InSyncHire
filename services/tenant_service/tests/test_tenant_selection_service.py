# LOCATION: services/tenant_service/tests/test_tenant_selection_service.py

import asyncio
import uuid

import pytest
from auth_tokens import TokenService, generate_rsa_keypair_pem
from cryptography.fernet import Fernet
from shared.db import make_session_factory
from tenant_service.models import GlobalBase
from tenant_service.repositories import MembershipRepository, OrganizationRepository
from tenant_service.services.tenant_selection_service import (
    MembershipInactiveError,
    NoMembershipError,
    TenantSelectionService,
)
from tenant_service.tenant_db import TenantResolver

from .conftest import build_fake_redis, build_global_test_engine, build_test_crypto, seed_active_tenant


def _build_token_service(redis) -> TokenService:
    private_pem, public_pem = generate_rsa_keypair_pem()
    return TokenService(
        private_key_pem=private_pem, public_key_pem=public_pem,
        fernet_key=Fernet.generate_key().decode(), redis=redis,
    )


def test_select_tenant_success():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        user_id = uuid.uuid4()
        tenant = await seed_active_tenant(session_factory, crypto, subdomain="acme")

        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
        session, _ = await resolver.get_session_for_tenant_id(tenant.tenant_id)
        org = await OrganizationRepository(session).create(tenant_id=tenant.tenant_id, name="Acme Corp")
        await MembershipRepository(session).create(
            user_id=user_id, tenant_id=tenant.tenant_id, org_id=org.org_id, role="recruiter"
        )
        await session.commit()
        await session.close()

        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        service = TenantSelectionService(tenant_resolver=resolver, token_service=token_service)

        result = await service.select(user_id=user_id, subdomain="acme", fingerprint="fp-1")
        assert result.role == "recruiter"
        assert result.tenant_id == tenant.tenant_id

        payload = await token_service.decode_and_verify(result.tokens.access_token, expected_type="access")
        assert payload.tenant_id == tenant.tenant_id
        assert payload.role == "recruiter"
        assert payload.org_id == org.org_id

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_select_tenant_no_membership_raises():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        await seed_active_tenant(session_factory, crypto, subdomain="acme")
        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)

        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        service = TenantSelectionService(tenant_resolver=resolver, token_service=token_service)

        with pytest.raises(NoMembershipError):
            await service.select(user_id=uuid.uuid4(), subdomain="acme", fingerprint="fp-1")

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_select_tenant_inactive_membership_raises():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        user_id = uuid.uuid4()
        tenant = await seed_active_tenant(session_factory, crypto, subdomain="acme")

        resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
        session, _ = await resolver.get_session_for_tenant_id(tenant.tenant_id)
        org = await OrganizationRepository(session).create(tenant_id=tenant.tenant_id, name="Acme Corp")
        membership = await MembershipRepository(session).create(
            user_id=user_id, tenant_id=tenant.tenant_id, org_id=org.org_id, role="observer"
        )
        membership.is_active = False
        await session.commit()
        await session.close()

        redis = build_fake_redis()
        token_service = _build_token_service(redis)
        service = TenantSelectionService(tenant_resolver=resolver, token_service=token_service)

        with pytest.raises(MembershipInactiveError):
            await service.select(user_id=user_id, subdomain="acme", fingerprint="fp-1")

        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())
