# LOCATION: services/tenant_service/tenant_service/cookies.py

"""
Cookie helpers, identical scheme to Auth Service's (Section 10c) --
Tenant Service re-issues the SAME cookies (same names, same flags) when
it hands out a tenant-scoped token, so the browser/client doesn't need
to know or care which service issued its current session.
"""

from __future__ import annotations

from fastapi import Response

from auth_tokens import IssuedTokenPair

from .config import TenantServiceConfig

ACCESS_COOKIE_NAME = "insynchire_access"
REFRESH_COOKIE_NAME = "insynchire_refresh"


def set_auth_cookies(response: Response, tokens: IssuedTokenPair, config: TenantServiceConfig) -> None:
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
