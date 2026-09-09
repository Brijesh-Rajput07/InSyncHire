# LOCATION: services/auth_service/auth_service/services/token_service.py

"""
Re-exports the shared token system (M3 moved the actual implementation
to shared/auth-tokens/auth_tokens/token_service.py, since Tenant
Service needs the exact same encrypted-JWT scheme to verify AND issue
tokens -- see that package's README for why this is shared rather than
duplicated).

This module exists so nothing else in auth_service (or its tests) had
to change import paths during the M3 refactor -- every name that used
to live here is still importable from here, just re-exported.
"""

from __future__ import annotations

from auth_tokens import (
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
