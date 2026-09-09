# LOCATION: services/user_profile_service/user_profile_service/auth_dependency.py

"""
Identity + candidate-only enforcement for FastAPI routes.

Reads the SAME `insynchire_access` cookie every other service reads,
using the shared `auth_tokens.TokenService` (Section 10c) -- same
fingerprint-re-validation discipline as tenant_service/auth_dependency.py
(FIX-M2).

Why this is NOT just `enforce_permission_matrix()` from `shared/permissions`
(unlike tenant_service, which uses that for all its routes): PERMISSION_MATRIX
scopes `/profile*` to `["candidate"]`, but candidate tokens are ALWAYS
issued with `role=None` (see models/global_models.py's docstring --
Auth Service never sets role="candidate" on any token, for anyone).
There is no way to satisfy `role in ["candidate"]` from the token alone.
So this service adds its own `get_current_candidate` dependency that:
  1. Verifies the token the normal way (signature, expiry, denylist,
     fingerprint) -- identical to every other service.
  2. Requires tenant_id/role to be UNSET (a company_user who has
     selected a tenant is never a candidate, by construction).
  3. Looks up the caller's account_type in insynchire_global (read-only
     -- see repositories/global_user_repository.py) and requires it to
     be exactly "candidate".
This keeps the actual authorization rule (candidate-only) enforced
server-side per Section: "RBAC ENFORCEMENT ... Checked server-side on
EVERY endpoint" -- just via account_type instead of a token role claim
that was never designed to carry this distinction.
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


async def get_current_candidate(identity: TokenPayload = Depends(get_current_identity)) -> TokenPayload:
    if _global_user_repository is None:
        raise RuntimeError("auth_dependency.configure() was never called at startup")

    if identity.tenant_id is not None or identity.role is not None:
        # A company_user who has selected a tenant (or been invited)
        # is never a candidate -- no need to even check account_type.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This endpoint is for candidate accounts only")

    try:
        account_type = await _global_user_repository.get_account_type(identity.user_id)
    except GlobalUserNotFoundError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from exc

    if account_type != "candidate":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This endpoint is for candidate accounts only")

    return identity