# LOCATION: shared/auth-tokens/auth_tokens/__init__.py

"""
Shared token issuance/verification package (Section 10c).

Every service that needs to know who's calling (via the httpOnly
cookie) or issue a new token (Auth Service at login/signup, Tenant
Service when granting a tenant-scoped session) imports from here rather
than reimplementing the encrypted-JWT scheme.
"""

from .schemas import TokenPayload
from .token_service import (
    IssuedTokenPair,
    TokenError,
    TokenExpiredError,
    TokenFingerprintMismatchError,
    TokenInvalidError,
    TokenRevokedError,
    TokenService,
    generate_rsa_keypair_pem,
    session_fingerprint,
)

__all__ = [
    "TokenPayload",
    "TokenService",
    "IssuedTokenPair",
    "TokenError",
    "TokenExpiredError",
    "TokenInvalidError",
    "TokenRevokedError",
    "TokenFingerprintMismatchError",
    "generate_rsa_keypair_pem",
    "session_fingerprint",
]
