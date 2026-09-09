# LOCATION: shared/auth-tokens/auth_tokens/token_service.py

"""
Token / cookie system (Section 10c).

This is a SHARED package (moved here from Auth Service during M3) so
any service can verify who's calling and, when it has the authority to
do so (e.g. Tenant Service issuing a tenant-scoped token after checking
membership), issue new tokens using the exact same scheme Auth Service
uses. Duplicating this logic per-service would risk two services
silently drifting out of sync on how tokens are built/verified — a
security-sensitive thing to get subtly wrong twice.

  - Token payload (user_id, tenant_id, org_id, role, session_fingerprint,
    issued_at, expires_at) is AES-256 (Fernet) encrypted BEFORE being
    placed in the JWT, so decoding the JWT without the Fernet key gives
    you ciphertext, not the actual claims.
  - The JWT itself is signed RS256.
  - Access tokens: 15 min. Refresh tokens: 7 days, rotated on every use.
  - Redis denylist: logout / role change / tenant suspension immediately
    invalidate a token by its jti.
  - Cookies: httpOnly, Secure, SameSite=Strict (Section 10c) — set by
    the route layer using the values this service returns; this module
    never touches `Request`/`Response` directly, keeping it framework-
    agnostic and independently testable.

Every service that verifies or issues tokens must be configured with
the SAME RS256 keypair and the SAME Fernet key as every other service —
these are shared secrets across the whole system, not per-service ones.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from redis.asyncio import Redis

from .schemas import TokenPayload


class TokenError(Exception):
    """Base class for all token validation failures."""


class TokenExpiredError(TokenError):
    pass


class TokenInvalidError(TokenError):
    pass


class TokenRevokedError(TokenError):
    pass


class TokenFingerprintMismatchError(TokenError):
    """Raised when a token is presented from a different device/network
    context than the one it was issued for (Section 10c: "session_fingerprint:
    hash(IP + User-Agent) embedded in token, re-checked on every request —
    token stolen from a different device/IP is rejected"). The mismatched
    token is also immediately revoked (see decode_and_verify)."""
    pass


def generate_rsa_keypair_pem() -> tuple[str, str]:
    """Generates an ephemeral RSA keypair for dev/test use when no real
    keys are configured. NEVER use the output of this in production —
    configure JWT_PRIVATE_KEY_PATH / JWT_PUBLIC_KEY_PATH instead so the
    same keypair persists across restarts (otherwise every restart
    invalidates every outstanding token)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


def session_fingerprint(ip_address: str, user_agent: str) -> str:
    """Hash of IP+UA embedded in the token to detect token theft
    (Section 10c) — if a stolen cookie is replayed from a different
    IP/UA, the fingerprint mismatch is detectable by the caller."""
    import hashlib

    return hashlib.sha256(f"{ip_address}|{user_agent}".encode("utf-8")).hexdigest()


@dataclass
class IssuedTokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


class TokenService:
    def __init__(
        self,
        *,
        private_key_pem: str,
        public_key_pem: str,
        fernet_key: str,
        redis: Redis,
        access_ttl_seconds: int = 15 * 60,
        refresh_ttl_seconds: int = 7 * 24 * 60 * 60,
    ):
        self._private_key = private_key_pem
        self._public_key = public_key_pem
        self._fernet = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
        self._redis = redis
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds

    def _encrypt_payload(self, payload: TokenPayload) -> str:
        return self._fernet.encrypt(payload.model_dump_json().encode("utf-8")).decode("utf-8")

    def _decrypt_payload(self, ciphertext: str) -> TokenPayload:
        try:
            plaintext = self._fernet.decrypt(ciphertext.encode("utf-8"))
        except InvalidToken as exc:
            raise TokenInvalidError("Could not decrypt token payload") from exc
        return TokenPayload.model_validate_json(plaintext)

    def _build_jwt(self, payload: TokenPayload) -> str:
        encrypted_data = self._encrypt_payload(payload)
        claims = {
            "data": encrypted_data,
            "jti": payload.jti,
            "exp": int(payload.expires_at.timestamp()),
            "iat": int(payload.issued_at.timestamp()),
        }
        return jwt.encode(claims, self._private_key, algorithm="RS256")

    async def issue_token_pair(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
        org_id: uuid.UUID | None,
        role: str | None,
        fingerprint: str,
    ) -> IssuedTokenPair:
        now = datetime.now(timezone.utc)
        access_expires = now + timedelta(seconds=self._access_ttl)
        refresh_expires = now + timedelta(seconds=self._refresh_ttl)

        access_payload = TokenPayload(
            user_id=user_id, tenant_id=tenant_id, org_id=org_id, role=role,
            session_fingerprint=fingerprint, issued_at=now, expires_at=access_expires,
            token_type="access", jti=secrets.token_hex(16),
        )
        refresh_payload = TokenPayload(
            user_id=user_id, tenant_id=tenant_id, org_id=org_id, role=role,
            session_fingerprint=fingerprint, issued_at=now, expires_at=refresh_expires,
            token_type="refresh", jti=secrets.token_hex(16),
        )

        return IssuedTokenPair(
            access_token=self._build_jwt(access_payload),
            refresh_token=self._build_jwt(refresh_payload),
            access_expires_at=access_expires,
            refresh_expires_at=refresh_expires,
        )

    async def decode_and_verify(
        self, token: str, *, expected_type: str | None = None, current_fingerprint: str | None = None
    ) -> TokenPayload:
        """Verifies JWT signature + expiry, checks the Redis denylist,
        decrypts the payload, optionally checks token_type, and — when
        `current_fingerprint` is provided — re-validates the session
        fingerprint against the one embedded at issuance (Section 10c).

        `current_fingerprint` is optional at the type level only so that
        internal call sites that already trust the token (e.g. `refresh()`
        below, which re-derives it from the payload itself) don't need to
        pass it — every caller decoding a token that arrived from an
        actual HTTP request MUST pass it. Skipping it silently reduces
        this to signature-only verification, defeating the theft-detection
        purpose of the fingerprint entirely.

        On mismatch, the token is immediately revoked (Section 10c:
        "mismatch = 401 Unauthorized with Redis denylist entry for that
        token") — a caller who got a fingerprint-mismatched token once
        cannot simply retry with the same token.
        """
        try:
            claims = jwt.decode(token, self._public_key, algorithms=["RS256"])
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError("Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenInvalidError(f"Invalid token: {exc}") from exc

        jti = claims.get("jti")
        if jti and await self._redis.exists(f"revoked_token:{jti}"):
            raise TokenRevokedError("Token has been revoked")

        payload = self._decrypt_payload(claims["data"])

        revoked_at_raw = await self._redis.get(f"revoked_user:{payload.user_id}")
        if revoked_at_raw is not None:
            revoked_at = datetime.fromtimestamp(float(revoked_at_raw), tz=timezone.utc)
            if payload.issued_at <= revoked_at:
                raise TokenRevokedError("All tokens for this user were revoked")

        if current_fingerprint is not None and current_fingerprint != payload.session_fingerprint:
            remaining = int((payload.expires_at - datetime.now(timezone.utc)).total_seconds())
            await self.revoke(payload.jti, max(remaining, 1))
            raise TokenFingerprintMismatchError(
                "Session fingerprint mismatch — token may have been stolen and replayed "
                "from a different device or network"
            )

        if expected_type is not None and payload.token_type != expected_type:
            raise TokenInvalidError(f"Expected a {expected_type} token, got {payload.token_type}")

        return payload

    async def revoke(self, jti: str, ttl_seconds: int) -> None:
        """Adds a token's jti to the Redis denylist for `ttl_seconds`
        (should be >= the token's remaining lifetime) — logout, role
        change, and tenant suspension all call this (Section 10c)."""
        await self._redis.set(f"revoked_token:{jti}", "1", ex=max(ttl_seconds, 1))

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        """Marks every token issued for `user_id` UP TO THIS MOMENT as
        revoked (role change, forced logout, tenant suspension —
        Section 10c). Tokens issued AFTER this call (e.g. the user
        logging back in) remain valid — this is a point-in-time cutoff,
        not a permanent block."""
        now_ts = datetime.now(timezone.utc).timestamp()
        await self._redis.set(f"revoked_user:{user_id}", str(now_ts), ex=self._refresh_ttl)

    async def refresh(self, refresh_token: str, *, current_fingerprint: str) -> IssuedTokenPair:
        """Rotation-on-use (Section 10c): validates the refresh token
        (including its session fingerprint — a stolen refresh token is
        longer-lived than an access token, making this check even more
        important here), revokes it immediately, and issues a brand new
        access+refresh pair. The old refresh token can never be used
        again even if intercepted."""
        payload = await self.decode_and_verify(
            refresh_token, expected_type="refresh", current_fingerprint=current_fingerprint
        )

        remaining = int((payload.expires_at - datetime.now(timezone.utc)).total_seconds())
        await self.revoke(payload.jti, max(remaining, 1))

        return await self.issue_token_pair(
            user_id=payload.user_id,
            tenant_id=payload.tenant_id,
            org_id=payload.org_id,
            role=payload.role,
            fingerprint=payload.session_fingerprint,
        )
