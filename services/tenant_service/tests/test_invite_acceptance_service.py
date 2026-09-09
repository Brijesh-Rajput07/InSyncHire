# LOCATION: services/tenant_service/tests/test_invite_acceptance_service.py

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from shared.db import make_session_factory
from tenant_service.models import GlobalBase, GlobalUser
from tenant_service.repositories import GlobalUserRepository, InviteRepository, OrganizationRepository
from tenant_service.services.invite_acceptance_service import (
    CandidateConfirmationRequiredError,
    InviteAlreadyAcceptedError,
    InviteExpiredError,
    InviteNotFoundError,
    InviteAcceptanceService,
    _hash_token,
)
from tenant_service.tenant_db import TenantResolver

from .conftest import build_global_test_engine, build_test_crypto, seed_active_tenant


async def _seed_and_resolve(session_factory, crypto, **kwargs):
    tenant = await seed_active_tenant(session_factory, crypto, **kwargs)
    resolver = TenantResolver(global_session_factory=session_factory, crypto=crypto)
    session, tenant_row = await resolver.get_session_for_tenant_id(tenant.tenant_id)
    return session, tenant_row, resolver


async def _seed_org_and_invite(session, tenant, *, token: str, expires_in_seconds: int, role="recruiter"):
    org = await OrganizationRepository(session).create(tenant_id=tenant.tenant_id, name=tenant.company_name)
    invite = await InviteRepository(session).create(
        tenant_id=tenant.tenant_id,
        email="newhire@acme-corp.com",
        role=role,
        invited_by=uuid.uuid4(),
        token_hash=_hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds),
    )
    await session.commit()
    return org, invite


async def _seed_global_user(session_factory, user_id: uuid.UUID, account_type: str) -> None:
    async with session_factory() as session:
        session.add(
            GlobalUser(user_id=user_id, email=f"{user_id.hex}@example.com", account_type=account_type, is_active=True)
        )
        await session.commit()


def test_accept_invite_success():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        session, tenant, resolver = await _seed_and_resolve(session_factory, crypto)
        await _seed_org_and_invite(session, tenant, token="plaintext-token-123", expires_in_seconds=3600)

        accepting_user_id = uuid.uuid4()
        service = InviteAcceptanceService()
        result = await service.accept(
            session=session, invite_token="plaintext-token-123", accepting_user_id=accepting_user_id
        )

        assert result.tenant_id == tenant.tenant_id
        assert result.role == "recruiter"
        assert result.org_id is not None

        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_accept_unknown_token_raises():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        session, tenant, resolver = await _seed_and_resolve(session_factory, crypto)
        service = InviteAcceptanceService()

        with pytest.raises(InviteNotFoundError):
            await service.accept(session=session, invite_token="nonexistent", accepting_user_id=uuid.uuid4())

        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_accept_expired_invite_raises():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        session, tenant, resolver = await _seed_and_resolve(session_factory, crypto)
        await _seed_org_and_invite(session, tenant, token="expired-token", expires_in_seconds=-10)

        service = InviteAcceptanceService()
        with pytest.raises(InviteExpiredError):
            await service.accept(session=session, invite_token="expired-token", accepting_user_id=uuid.uuid4())

        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_accept_already_accepted_invite_raises():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        session, tenant, resolver = await _seed_and_resolve(session_factory, crypto)
        await _seed_org_and_invite(session, tenant, token="reused-token", expires_in_seconds=3600)

        service = InviteAcceptanceService()
        await service.accept(session=session, invite_token="reused-token", accepting_user_id=uuid.uuid4())

        with pytest.raises(InviteAlreadyAcceptedError):
            await service.accept(session=session, invite_token="reused-token", accepting_user_id=uuid.uuid4())

        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


# --- FIX-M3: existing-user (candidate account) confirmation flow ---

def test_accept_requires_confirmation_for_candidate_account():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        session, tenant, resolver = await _seed_and_resolve(session_factory, crypto)
        await _seed_org_and_invite(session, tenant, token="candidate-token", expires_in_seconds=3600)

        candidate_user_id = uuid.uuid4()
        await _seed_global_user(session_factory, candidate_user_id, "candidate")

        service = InviteAcceptanceService(global_user_repository=GlobalUserRepository(session_factory))

        with pytest.raises(CandidateConfirmationRequiredError):
            await service.accept(
                session=session, invite_token="candidate-token", accepting_user_id=candidate_user_id,
                confirmed=False,
            )

        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_accept_succeeds_for_candidate_account_when_confirmed():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        session, tenant, resolver = await _seed_and_resolve(session_factory, crypto)
        await _seed_org_and_invite(session, tenant, token="candidate-token-2", expires_in_seconds=3600)

        candidate_user_id = uuid.uuid4()
        await _seed_global_user(session_factory, candidate_user_id, "candidate")

        service = InviteAcceptanceService(global_user_repository=GlobalUserRepository(session_factory))

        result = await service.accept(
            session=session, invite_token="candidate-token-2", accepting_user_id=candidate_user_id,
            confirmed=True,
        )
        assert result.role == "recruiter"

        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_accept_does_not_require_confirmation_for_company_user_account():
    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        session, tenant, resolver = await _seed_and_resolve(session_factory, crypto)
        await _seed_org_and_invite(session, tenant, token="company-user-token", expires_in_seconds=3600)

        company_user_id = uuid.uuid4()
        await _seed_global_user(session_factory, company_user_id, "company_user")

        service = InviteAcceptanceService(global_user_repository=GlobalUserRepository(session_factory))

        # No confirmation needed/passed -- succeeds directly since this
        # account is already a company_user, not a candidate.
        result = await service.accept(
            session=session, invite_token="company-user-token", accepting_user_id=company_user_id,
        )
        assert result.role == "recruiter"

        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())


def test_accept_skips_confirmation_check_when_no_repository_configured():
    """Backward-compatible default: a service constructed without a
    global_user_repository (existing call sites/tests) never gates on
    account_type at all."""

    async def _run():
        engine = build_global_test_engine()
        async with engine.begin() as conn:
            await conn.run_sync(GlobalBase.metadata.create_all)
        session_factory = make_session_factory(engine)
        crypto = build_test_crypto()

        session, tenant, resolver = await _seed_and_resolve(session_factory, crypto)
        await _seed_org_and_invite(session, tenant, token="no-gate-token", expires_in_seconds=3600)

        service = InviteAcceptanceService()  # no global_user_repository passed
        result = await service.accept(
            session=session, invite_token="no-gate-token", accepting_user_id=uuid.uuid4()
        )
        assert result.role == "recruiter"

        await session.close()
        await resolver.dispose_all()
        await engine.dispose()

    asyncio.run(_run())
