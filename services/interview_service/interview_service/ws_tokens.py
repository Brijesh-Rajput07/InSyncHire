# LOCATION: services/interview_service/interview_service/ws_tokens.py

"""
Short-lived, signed WebSocket connect token (Section 10e: "Auth at
handshake: short-lived signed token in connection URL").

This is a DIFFERENT concern from `crypto.RoomTokenCrypto`'s
`interview_sessions.room_token`: that value is a session-wide, opaque
identifier a future SFU integration (video/voice, Section 10f) would
use, the same for every participant. THIS token is per-participant,
per-join, embeds the caller's identity (`tenant_id`, `session_id`,
`user_id`, `role_in_session`), and expires quickly (`ttl_seconds`,
default 5 minutes) — exactly the "short-lived signed token" Section 10e
calls for so the WebSocket gateway can authorize a connection from the
URL alone, without needing the caller's httpOnly cookie (browsers don't
send cookies on WebSocket upgrade requests to a different path/origin
reliably in all deployment topologies, so a token-in-URL is the
standard approach for WS auth).

Reuses `RoomTokenCrypto`'s underlying Fernet mechanics (both are
short-lived, session-scoped join credentials with the same trust
boundary — unlike `ConnectionStringCrypto`, which protects a much
higher-blast-radius secret), but is its own class with its own payload
shape and its own expiry semantics, not a call-site reuse of
`RoomTokenCrypto`'s public methods directly.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .crypto import RoomTokenCrypto


class WSTokenError(Exception):
    """Base class for WebSocket connect token failures."""


class WSTokenInvalidError(WSTokenError):
    def __init__(self):
        super().__init__("Invalid WebSocket connect token")


class WSTokenExpiredError(WSTokenError):
    def __init__(self):
        super().__init__("WebSocket connect token has expired")


@dataclass
class WSTokenClaims:
    tenant_id: uuid.UUID
    session_id: uuid.UUID
    user_id: uuid.UUID
    role_in_session: str
    expires_at: datetime


class WSConnectTokenService:
    def __init__(self, *, crypto: RoomTokenCrypto, ttl_seconds: int = 300):
        self._crypto = crypto
        self._ttl_seconds = ttl_seconds

    def issue(
        self,
        *,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        role_in_session: str,
    ) -> str:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)
        payload = {
            "tenant_id": str(tenant_id),
            "session_id": str(session_id),
            "user_id": str(user_id),
            "role_in_session": role_in_session,
            "expires_at": expires_at.isoformat(),
        }
        return self._crypto.encrypt(json.dumps(payload))

    def verify(self, token: str) -> WSTokenClaims:
        try:
            raw = self._crypto.decrypt(token)
            data = json.loads(raw)
            expires_at = datetime.fromisoformat(data["expires_at"])
            claims = WSTokenClaims(
                tenant_id=uuid.UUID(data["tenant_id"]),
                session_id=uuid.UUID(data["session_id"]),
                user_id=uuid.UUID(data["user_id"]),
                role_in_session=data["role_in_session"],
                expires_at=expires_at,
            )
        except Exception as exc:  # noqa: BLE001 - any malformed/tampered token is equally invalid
            raise WSTokenInvalidError() from exc

        if datetime.now(timezone.utc) >= claims.expires_at:
            raise WSTokenExpiredError()
        return claims