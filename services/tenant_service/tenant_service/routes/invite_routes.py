# LOCATION: services/tenant_service/tenant_service/routes/invite_routes.py

"""Invite creation (company_admin only) + acceptance (Task F)."""

from __future__ import annotations

import uuid

from auth_tokens import TokenPayload, TokenService, session_fingerprint
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..auth_dependency import enforce_permission_matrix
from ..config import get_config
from ..cookies import set_auth_cookies
from ..dependencies import (
    get_global_tenant_repository,
    get_invite_acceptance_service,
    get_invite_service,
    get_tenant_resolver,
    get_token_service,
)
from ..repositories import GlobalTenantRepository
from ..schemas import AcceptInviteRequest, AcceptInviteResponse, InviteUserRequest, InviteUserResponse
from ..services import (
    AlreadyInvitedError,
    CandidateConfirmationRequiredError,
    EmailDomainMismatchError,
    InviteAcceptanceService,
    InviteAlreadyAcceptedError,
    InviteExpiredError,
    InviteNotFoundError,
    InviteService,
)
from ..tenant_db import TenantResolver

router = APIRouter(prefix="/tenant")


def _trace_id(request: Request) -> str:
    return request.headers.get("x-trace-id", str(uuid.uuid4()))


def _fingerprint(request: Request) -> str:
    return session_fingerprint(
        ip_address=request.client.host if request.client else "unknown",
        user_agent=request.headers.get("user-agent", "unknown"),
    )


@router.post("/invites", response_model=InviteUserResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: InviteUserRequest,
    request: Request,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    invite_service: InviteService = Depends(get_invite_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    session, tenant = await tenant_resolver.get_session_for_tenant_id(identity.tenant_id)
    try:
        try:
            result = await invite_service.create_invite(
                session=session,
                tenant=tenant,
                invited_by=identity.user_id,
                email=body.email,
                role=body.role,
                trace_id=_trace_id(request),
            )
        except EmailDomainMismatchError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except AlreadyInvitedError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    finally:
        await session.close()

    return InviteUserResponse(
        invite_id=result.invite_id, email=result.email, role=result.role, expires_at=result.expires_at
    )


@router.post("/invites/accept", response_model=AcceptInviteResponse, status_code=status.HTTP_200_OK)
async def accept_invite(
    body: AcceptInviteRequest,
    request: Request,
    response: Response,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    acceptance_service: InviteAcceptanceService = Depends(get_invite_acceptance_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
    global_tenant_repository: GlobalTenantRepository = Depends(get_global_tenant_repository),
    token_service: TokenService = Depends(get_token_service),
):
    # The invite table is per-tenant-DB, so we need to know WHICH
    # tenant before we can even look the token up. In practice the
    # invitee's link encodes the subdomain (e.g.
    # https://acme.insynchire.com/accept-invite?token=...) and the
    # frontend sends that along as a header.
    subdomain = request.headers.get("x-tenant-subdomain")
    if not subdomain:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Missing X-Tenant-Subdomain header -- which company is this invite for?",
        )

    session, tenant = await tenant_resolver.get_session_for_subdomain(subdomain)
    try:
        try:
            result = await acceptance_service.accept(
                session=session,
                invite_token=body.invite_token,
                accepting_user_id=identity.user_id,
                confirmed=body.confirm_candidate_to_company_access,
            )
        except InviteNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except InviteExpiredError as exc:
            raise HTTPException(
                status.HTTP_410_GONE, "Invite expired, ask your admin to resend"
            ) from exc
        except InviteAlreadyAcceptedError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "Invite already used") from exc
        except CandidateConfirmationRequiredError as exc:
            # FIX-M3: distinct status so the frontend can show the
            # "You have a candidate account... Continue?" prompt and
            # resubmit with confirm_candidate_to_company_access=true,
            # rather than this looking like a generic error.
            raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, str(exc)) from exc
    finally:
        await session.close()

    # Immediately issue a tenant-scoped token, same as tenant selection --
    # the user shouldn't have to separately "select" the tenant they
    # were just invited into.
    tokens = await token_service.issue_token_pair(
        user_id=identity.user_id,
        tenant_id=result.tenant_id,
        org_id=result.org_id,
        role=result.role,
        fingerprint=_fingerprint(request),
    )
    set_auth_cookies(response, tokens, get_config())

    return AcceptInviteResponse(
        membership_id=result.membership_id, tenant_id=result.tenant_id, role=result.role
    )
