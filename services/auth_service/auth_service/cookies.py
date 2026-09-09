# LOCATION: services/auth_service/auth_service/cookies.py

"""
Cookie helpers (Section 10c): Secure, HttpOnly, SameSite=Strict,
short-lived access + longer-lived rotating refresh cookie.
"""

from __future__ import annotations

from fastapi import Response

from .config import AuthServiceConfig
from .services.token_service import IssuedTokenPair

ACCESS_COOKIE_NAME = "insynchire_access"
REFRESH_COOKIE_NAME = "insynchire_refresh"


def set_auth_cookies(response: Response, tokens: IssuedTokenPair, config: AuthServiceConfig) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=tokens.access_token,
        max_age=config.access_token_ttl_seconds,
        httponly=True,
        secure=config.cookie_secure,
        samesite="strict",
        domain=config.cookie_domain,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=tokens.refresh_token,
        max_age=config.refresh_token_ttl_seconds,
        httponly=True,
        secure=config.cookie_secure,
        samesite="strict",
        domain=config.cookie_domain,
        path="/",
    )


def clear_auth_cookies(response: Response, config: AuthServiceConfig) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/", domain=config.cookie_domain)
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/", domain=config.cookie_domain)
