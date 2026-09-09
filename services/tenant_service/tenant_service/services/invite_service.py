# LOCATION: services/tenant_service/tenant_service/services/invite_service.py

"""
company_admin invites a user by email (Task F). Validates the invitee's
email domain matches the TENANT'S OWN domain (Section 1: "invitation
validated that invitee email matches tenant's domain") — this is a
simple exact-match check against `tenants.company_domain`, not a fresh
MX-record lookup (that already happened once, at the tenant's own
signup in Auth Service).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from insynchire_events import Topics
from insynchire_events.schemas import UserInvitedEvent
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Tenant
from ..repositories import InviteRepository


class InviteError(Exception):
    """Base class for invite creation failures."""


class EmailDomainMismatchError(InviteError):
    def __init__(self, email: str, expected_domain: str):
        super().__init__(
            f"'{email}' does not match this company's domain (@{expected_domain}). "
            "Invites can only be sent to addresses on your own corporate domain."
        )


class AlreadyInvitedError(InviteError):
    def __init__(self, email: str):
        super().__init__(f"'{email}' already has a pending invite")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class CreateInviteResult:
    invite_id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    invite_token: str  # PLAINTEXT -- only ever returned once, to be emailed


class InviteService:
    def __init__(self, *, ttl_seconds: int, publish, debug_log: bool = False):
        self._ttl_seconds = ttl_seconds
        self._publish = publish
        self._debug_log = debug_log

    async def create_invite(
        self,
        *,
        session: AsyncSession,
        tenant: Tenant,
        invited_by: uuid.UUID,
        email: str,
        role: str,
        trace_id: str,
    ) -> CreateInviteResult:
        invitee_domain = email.rsplit("@", 1)[-1].lower()
        if invitee_domain != tenant.company_domain.lower():
            raise EmailDomainMismatchError(email, tenant.company_domain)

        invite_repo = InviteRepository(session)
        if await invite_repo.get_pending_by_email(tenant.tenant_id, email.lower()) is not None:
            raise AlreadyInvitedError(email)

        plaintext_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)

        invite = await invite_repo.create(
            tenant_id=tenant.tenant_id,
            email=email.lower(),
            role=role,
            invited_by=invited_by,
            token_hash=_hash_token(plaintext_token),
            expires_at=expires_at,
        )
        await session.commit()

        if self._debug_log:
            import logging

            logging.getLogger("tenant_service.invite").info(
                "[DEV ONLY] invite token for %s (tenant=%s, role=%s): %s",
                email, tenant.subdomain, role, plaintext_token,
            )

        await self._publish(
            Topics.USER_INVITED.value,
            UserInvitedEvent(
                trace_id=trace_id,
                invite_id=invite.invite_id,
                email=invite.email,
                role=role,
                invited_by=invited_by,
                tenant_id=tenant.tenant_id,
            ),
        )

        return CreateInviteResult(
            invite_id=invite.invite_id,
            email=invite.email,
            role=invite.role,
            expires_at=invite.expires_at,
            invite_token=plaintext_token,
        )
