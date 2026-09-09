# LOCATION: services/auth_service/auth_service/routes/auth_routes.py

"""Login / refresh / logout routes (Task D)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..cookies import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME, clear_auth_cookies, set_auth_cookies
from ..dependencies import get_global_session, get_login_service, get_token_service
from ..schemas import LoginRequest, LoginResponse
from ..services import AccountInactiveError, InvalidCredentialsError, TokenService, session_fingerprint
from ..services.login_service import LoginService
from ..services.token_service import (
    TokenError,
    TokenExpiredError,
    TokenFingerprintMismatchError,
    TokenInvalidError,
    TokenRevokedError,
)

router = APIRouter(prefix="/auth")


def _fingerprint(request: Request) -> str:
    return session_fingerprint(
        ip_address=request.client.host if request.client else "unknown",
        user_agent=request.headers.get("user-agent", "unknown"),
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    service: LoginService = Depends(get_login_service),
    session: AsyncSession = Depends(get_global_session),
):
    try:
        result = await service.login(
            session=session, email=body.email, password=body.password, fingerprint=_fingerprint(request)
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except AccountInactiveError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

    set_auth_cookies(response, result.tokens, get_config())
    return LoginResponse(
        user_id=result.user.user_id, email=result.user.email, account_type=result.user.account_type
    )


@router.post("/refresh", status_code=status.HTTP_200_OK)
async def refresh(
    request: Request,
    response: Response,
    token_service: TokenService = Depends(get_token_service),
):
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token cookie present")

    try:
        new_tokens = await token_service.refresh(refresh_token, current_fingerprint=_fingerprint(request))
    except TokenExpiredError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token expired, please log in again") from exc
    except TokenFingerprintMismatchError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session verification failed, please log in again") from exc
    except TokenRevokedError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session has been revoked, please log in again") from exc
    except (TokenInvalidError, TokenError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc

    set_auth_cookies(response, new_tokens, get_config())
    return {"message": "Token refreshed"}


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    request: Request,
    response: Response,
    token_service: TokenService = Depends(get_token_service),
):
    """Revokes both cookies' jti in the Redis denylist (Section 10c:
    "logout ... immediately invalidates tokens") and clears the
    cookies client-side."""
    config = get_config()
    for cookie_name, expected_type in (
        (ACCESS_COOKIE_NAME, "access"),
        (REFRESH_COOKIE_NAME, "refresh"),
    ):
        token = request.cookies.get(cookie_name)
        if not token:
            continue
        try:
            payload = await token_service.decode_and_verify(
                token, expected_type=expected_type, current_fingerprint=_fingerprint(request)
            )
            remaining = int((payload.expires_at - datetime.now(timezone.utc)).total_seconds())
            await token_service.revoke(payload.jti, max(remaining, 1))
        except TokenError:
            pass  # already invalid/expired/mismatched -- decode_and_verify already
            # revoked it in the mismatch case; either way nothing further to do here

    clear_auth_cookies(response, config)
    return {"message": "Logged out"}
