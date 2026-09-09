# LOCATION: services/tenant_service/tenant_service/services/invite_acceptance_service.py

"""On acceptance, assign the specified role in `tenant_user_memberships`
(Task F, final step).

FIX-M3 addition: "existing user" handling. Because our invite-accept
flow requires the accepter to already be authenticated (their own
global identity, via `get_current_identity`/`enforce_permission_matrix`
in the route layer), most of the ambiguity Section 4's FIX-M3 describes
("does invitee@example.com already have an account?") is already
resolved by construction — `accepting_user_id` IS an existing
`global_users.user_id` by the time we get here, whether they signed up
moments ago or years ago. The one piece that still needs explicit
handling: if that existing account is a `candidate` account_type, the
plan requires an explicit confirmation before silently also granting
them company-side access (a candidate might not expect that applying
for a job at Company A also gives Company B's invite instant access to
their "professional" identity). See `confirmed` below.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories import GlobalUserRepository, InviteRepository, MembershipRepository, OrganizationRepository


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_aware_utc(dt: datetime) -> datetime:
    """Some DB drivers (notably SQLite, used in this repo's tests) don't
    round-trip timezone info even on a `DateTime(timezone=True)` column
    the way Postgres does -- they hand back a naive datetime. We always
    stored these as UTC, so a naive value is assumed to already be UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class InviteAcceptanceError(Exception):
    """Base class for invite acceptance failures."""


class InviteNotFoundError(InviteAcceptanceError):
    def __init__(self):
        super().__init__("Invite not found or already used")


class InviteExpiredError(InviteAcceptanceError):
    def __init__(self):
        super().__init__("This invite has expired. Ask your company_admin to send a new one.")


class InviteAlreadyAcceptedError(InviteAcceptanceError):
    def __init__(self):
        super().__init__("This invite has already been accepted")


class CandidateConfirmationRequiredError(InviteAcceptanceError):
    """FIX-M3: raised (instead of silently proceeding) when the
    accepting account_type is `candidate` and the caller hasn't passed
    `confirmed=True` yet — the route layer surfaces this as a distinct
    response so the frontend can show: "You have a candidate account.
    Joining this company will also give you access as a
    recruiter/interviewer. Continue?" and resubmit with confirmation."""

    def __init__(self):
        super().__init__(
            "This account is a candidate account. Confirm to also grant company access."
        )


@dataclass
class AcceptInviteResult:
    membership_id: uuid.UUID
    tenant_id: uuid.UUID
    org_id: uuid.UUID
    role: str


class InviteAcceptanceService:
    def __init__(self, *, global_user_repository: GlobalUserRepository | None = None):
        # Optional so existing call sites/tests that don't care about
        # the candidate-confirmation path (most of them -- it's an edge
        # case) don't need to construct one. If omitted, the
        # confirmation check is skipped entirely (treated as already
        # confirmed) -- routes that DO want it enforced must pass it.
        self._global_user_repository = global_user_repository

    async def accept(
        self,
        *,
        session: AsyncSession,
        invite_token: str,
        accepting_user_id: uuid.UUID,
        confirmed: bool = False,
    ) -> AcceptInviteResult:
        invite_repo = InviteRepository(session)
        invite = await invite_repo.get_by_token_hash(_hash_token(invite_token))
        if invite is None:
            raise InviteNotFoundError()
        if invite.is_accepted:
            raise InviteAlreadyAcceptedError()
        if _as_aware_utc(invite.expires_at) <= datetime.now(timezone.utc):
            raise InviteExpiredError()

        if self._global_user_repository is not None and not confirmed:
            account_type = await self._global_user_repository.get_account_type(accepting_user_id)
            if account_type == "candidate":
                raise CandidateConfirmationRequiredError()

        org = await OrganizationRepository(session).get_by_tenant_id(invite.tenant_id)
        if org is None:
            # Shouldn't happen in practice -- the org is created the
            # moment the tenant is created (tenant_provisioning_consumer_service),
            # well before any invite could exist for it.
            raise InviteAcceptanceError("Tenant organization not found")

        membership = await MembershipRepository(session).create(
            user_id=accepting_user_id,
            tenant_id=invite.tenant_id,
            org_id=org.org_id,
            role=invite.role,
            invited_by=invite.invited_by,
        )
        await invite_repo.mark_accepted(invite)
        await session.commit()

        return AcceptInviteResult(
            membership_id=membership.membership_id,
            tenant_id=invite.tenant_id,
            org_id=org.org_id,
            role=invite.role,
        )
