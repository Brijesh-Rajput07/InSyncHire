# LOCATION: services/tenant_service/tenant_service/services/tenant_selection_service.py

"""
"Select active tenant" — closes the gap noted in Auth Service's
LoginService docstring (M2): a company_user's global login token has
tenant_id/org_id/role unset, since Auth Service has no way to know
which tenant/role applies. Here, given the caller's already-verified
global identity (user_id, from their existing access token) and a
target tenant (by subdomain), we check their membership in THAT
tenant's DB and, if found, issue a brand new token pair with
tenant_id/org_id/role populated.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from auth_tokens import IssuedTokenPair, TokenService

from ..repositories import MembershipRepository
from ..tenant_db import TenantResolver


class TenantSelectionError(Exception):
    """Base class for tenant selection failures."""


class NoMembershipError(TenantSelectionError):
    def __init__(self, user_id: uuid.UUID, subdomain: str):
        super().__init__(f"User {user_id} has no membership in tenant '{subdomain}'")


class MembershipInactiveError(TenantSelectionError):
    def __init__(self):
        super().__init__("Your membership in this organization has been deactivated")


@dataclass
class SelectTenantResult:
    tenant_id: uuid.UUID
    org_id: uuid.UUID
    role: str
    tokens: IssuedTokenPair


class TenantSelectionService:
    def __init__(self, *, tenant_resolver: TenantResolver, token_service: TokenService):
        self._tenant_resolver = tenant_resolver
        self._token_service = token_service

    async def select(
        self, *, user_id: uuid.UUID, subdomain: str, fingerprint: str
    ) -> SelectTenantResult:
        session, tenant = await self._tenant_resolver.get_session_for_subdomain(subdomain)
        try:
            membership = await MembershipRepository(session).get_by_user_and_tenant(
                user_id, tenant.tenant_id
            )
        finally:
            await session.close()

        if membership is None:
            raise NoMembershipError(user_id, subdomain)
        if not membership.is_active:
            raise MembershipInactiveError()

        tokens = await self._token_service.issue_token_pair(
            user_id=user_id,
            tenant_id=tenant.tenant_id,
            org_id=membership.org_id,
            role=membership.role,
            fingerprint=fingerprint,
        )

        return SelectTenantResult(
            tenant_id=tenant.tenant_id, org_id=membership.org_id, role=membership.role, tokens=tokens
        )
