# LOCATION: services/interview_service/interview_service/auth_dependency.py

"""
Identity + role/candidate enforcement for FastAPI routes. Interview
Service needs THREE enforcement styles, same reasoning `job_service`
already documented for needing two of them:

  1. `enforce_permission_matrix()` -- for recruiter/company_admin
     routes (`POST /interviews/schedule`) and the general staff read
     route (`GET /interviews/{id}`). These callers have a real,
     tenant-scoped token (role + tenant_id set), so the shared
     `permissions.PERMISSION_MATRIX` (FIX-M3) is enforced directly
     against `role`.

  2. `get_current_candidate()` -- not actually used by any route in
     THIS milestone (Interview Service has no route that is
     candidate-ONLY), but kept for parity/future use (e.g. a future
     "my interviews" listing) and because `resolve_join_identity` below
     reuses its exact account_type-checking logic.

  3. `resolve_join_identity()` -- `POST /interviews/{id}/join` is the
     one route in this service that must accept BOTH a staff caller
     (tenant-scoped token, role from the token) AND a candidate caller
     (global token, role=None, no tenant context at all -- Section 1:
     candidates are global, never tenant-scoped). `PERMISSION_MATRIX`'s
     `POST /interviews/{id}/join` entry lists all five roles including
     `candidate`, but a candidate token can never satisfy
     `enforce_permission_matrix()`'s `role in allowed_roles` check
     (candidate tokens are always issued with role=None -- see
     `job_service`/`user_profile_service`'s identical note). This
     dependency branches: if the token already carries a tenant_id +
     role, trust those (a staff caller, tenant known from their own
     token); otherwise, verify the account is genuinely a candidate via
     a read-only `global_users` lookup and require the SAME
     `X-Tenant-Id` header convention `job_service`'s candidate
     apply/my-application routes already established for "a candidate
     token has no tenant context, so the caller must say which
     tenant's interview this is."
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from auth_tokens import (
    TokenExpiredError,
    TokenFingerprintMismatchError,
    TokenInvalidError,
    TokenPayload,
    TokenRevokedError,
    TokenService,
    session_fingerprint,
)

from .repositories import GlobalUserNotFoundError, GlobalUserRepository

ACCESS_COOKIE_NAME = "insynchire_access"

STAFF_ROLES_FOR_JOIN = {"company_admin", "recruiter", "interviewer", "observer"}

_token_service: TokenService | None = None
_global_user_repository: GlobalUserRepository | None = None


def configure(token_service: TokenService, global_user_repository: GlobalUserRepository) -> None:
    global _token_service, _global_user_repository
    _token_service = token_service
    _global_user_repository = global_user_repository


def _current_fingerprint(request: Request) -> str:
    return session_fingerprint(
        ip_address=request.client.host if request.client else "unknown",
        user_agent=request.headers.get("user-agent", "unknown"),
    )


async def get_current_identity(request: Request) -> TokenPayload:
    if _token_service is None:
        raise RuntimeError("auth_dependency.configure() was never called at startup")

    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        return await _token_service.decode_and_verify(
            token, expected_type="access", current_fingerprint=_current_fingerprint(request)
        )
    except TokenExpiredError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please log in again") from exc
    except TokenFingerprintMismatchError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session verification failed, please log in again") from exc
    except TokenRevokedError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session has been revoked") from exc
    except TokenInvalidError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from exc


def enforce_permission_matrix():
    """For recruiter/company_admin/interviewer/observer routes -- role
    comes straight from the token (Tenant Service already put a real
    tenant/org/role on it). Fails closed (`is_allowed` returns False
    for unmapped routes)."""

    async def _check(request: Request, identity: TokenPayload = Depends(get_current_identity)) -> TokenPayload:
        from permissions import is_allowed

        if identity.tenant_id is None or identity.role is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "No active tenant context — select a tenant first"
            )
        if not is_allowed(request.method, request.url.path, identity.role):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{identity.role}' is not permitted to {request.method} {request.url.path}",
            )
        return identity

    return _check


async def get_current_candidate(identity: TokenPayload = Depends(get_current_identity)) -> TokenPayload:
    if _global_user_repository is None:
        raise RuntimeError("auth_dependency.configure() was never called at startup")

    if identity.tenant_id is not None or identity.role is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This endpoint is for candidate accounts only")

    try:
        account_type = await _global_user_repository.get_account_type(identity.user_id)
    except GlobalUserNotFoundError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from exc

    if account_type != "candidate":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This endpoint is for candidate accounts only")

    return identity


@dataclass
class InterviewAccessIdentity:
    user_id: uuid.UUID
    role_in_session: str  # company_admin | recruiter | interviewer | observer | candidate
    tenant_id: uuid.UUID


def _require_tenant_id_header(request: Request) -> uuid.UUID:
    raw = request.headers.get("x-tenant-id")
    if not raw:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Missing X-Tenant-Id header -- which company's interview is this? "
            "(the interview invite/notification should carry the tenant_id for exactly this purpose)",
        )
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Tenant-Id header is not a valid UUID") from exc


async def resolve_join_identity(
    request: Request, identity: TokenPayload = Depends(get_current_identity)
) -> InterviewAccessIdentity:
    """Branches on whether the token already carries a tenant-scoped
    role (staff) or not (candidate) -- see module docstring."""
    if identity.tenant_id is not None and identity.role is not None:
        if identity.role not in STAFF_ROLES_FOR_JOIN:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Role '{identity.role}' cannot join interview sessions"
            )
        return InterviewAccessIdentity(
            user_id=identity.user_id, role_in_session=identity.role, tenant_id=identity.tenant_id
        )

    if _global_user_repository is None:
        raise RuntimeError("auth_dependency.configure() was never called at startup")

    try:
        account_type = await _global_user_repository.get_account_type(identity.user_id)
    except GlobalUserNotFoundError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from exc

    if account_type != "candidate":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to join this interview")

    tenant_id = _require_tenant_id_header(request)
    return InterviewAccessIdentity(user_id=identity.user_id, role_in_session="candidate", tenant_id=tenant_id)