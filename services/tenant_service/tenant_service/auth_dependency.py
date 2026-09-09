# LOCATION: services/tenant_service/tenant_service/auth_dependency.py

"""
Identity + role enforcement for FastAPI routes (RBAC ENFORCEMENT RULES:
"Role checked server-side on EVERY endpoint" — client-supplied role
claims are never trusted; role always comes from the server-issued,
encrypted token, decoded here).

This reads the SAME `insynchire_access` cookie Auth Service issues,
using the shared `auth_tokens.TokenService` — see that package's README
for why the keys must match across services.

`configure()` is called once at app startup (dependencies.py) with the
real TokenService instance. Tests override `get_current_identity`
directly via `app.dependency_overrides` rather than touching this
module-level state, keeping the override mechanism test-only.
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

ACCESS_COOKIE_NAME = "insynchire_access"

_token_service: TokenService | None = None


def configure(token_service: TokenService) -> None:
    global _token_service
    _token_service = token_service


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
        # FIX-M2: re-validated on every request. The mismatched token is
        # already revoked as a side effect inside decode_and_verify.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session verification failed, please log in again") from exc
    except TokenRevokedError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session has been revoked") from exc
    except TokenInvalidError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from exc


def require_role(*allowed_roles: str):
    """Dependency factory: `Depends(require_role("company_admin"))`.
    Raises 401 if there's no tenant context on the token at all (e.g. a
    company_user who hasn't selected a tenant yet), 403 if the role
    doesn't match.

    Superseded by `enforce_permission_matrix()` below (FIX-M3) for
    routes that have a PERMISSION_MATRIX entry — kept here for any
    call site that genuinely needs an ad-hoc role check the matrix
    doesn't cover, but new routes should prefer the matrix so
    permissions stay defined in exactly one place (Section 4a)."""

    async def _check(identity: TokenPayload = Depends(get_current_identity)) -> TokenPayload:
        if identity.role is None or identity.tenant_id is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "No active tenant context — select a tenant first"
            )
        if identity.role not in allowed_roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires one of roles: {allowed_roles}")
        return identity

    return _check


def enforce_permission_matrix():
    """FIX-M3: dependency driven by the single canonical PERMISSION_MATRIX
    (`shared/permissions`) instead of a hardcoded role list at each route
    — "Never define permissions inline in routes" (Section 4a).

    Assumes the route always requires authentication first (true for
    every current Tenant Service route — none are `public` in the
    matrix); a route whose matrix entry is `"*"` still requires *some*
    valid identity, just no specific role. `is_allowed` fails closed:
    a route with no matrix entry at all is denied, not silently permitted.
    """

    async def _check(request: Request, identity: TokenPayload = Depends(get_current_identity)) -> TokenPayload:
        from permissions import is_allowed

        if not is_allowed(request.method, request.url.path, identity.role):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{identity.role}' is not permitted to {request.method} {request.url.path}",
            )
        return identity

    return _check
