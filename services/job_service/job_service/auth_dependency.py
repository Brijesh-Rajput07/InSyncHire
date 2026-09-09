# LOCATION: services/job_service/job_service/auth_dependency.py

"""
Identity + role/candidate enforcement for FastAPI routes. Job Service
needs BOTH enforcement styles other services use separately:

  1. `enforce_permission_matrix()` -- for recruiter/company_admin
     routes (job CRUD, applicant review). These callers DO have a
     real, tenant-scoped token (role + tenant_id set, from Tenant
     Service's tenant-selection or invite-acceptance flow), so the
     shared `permissions.PERMISSION_MATRIX` (FIX-M3) can be enforced
     directly against `role`, exactly like Tenant Service does.

  2. `get_current_candidate()` -- for candidate-facing routes (apply,
     my-application). Candidate tokens are ALWAYS issued with
     role=None (see user_profile_service/auth_dependency.py's
     docstring for the full explanation -- Auth Service never sets
     role="candidate" on any token, for anyone). So these routes
     cannot be enforced via PERMISSION_MATRIX's `["candidate"]` entries
     either; this dependency additionally checks account_type via a
     read-only insynchire_global.global_users lookup, same pattern
     used in user_profile_service.
"""

from __future__ import annotations

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
    """For recruiter/company_admin routes -- role comes straight from
    the token (Tenant Service already put a real tenant/org/role on it).
    Fails closed (`is_allowed` returns False for unmapped routes)."""

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