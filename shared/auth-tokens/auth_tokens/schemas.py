# LOCATION: shared/auth-tokens/auth_tokens/schemas.py

"""The shape of data that gets AES-encrypted and embedded in every JWT."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class TokenPayload(BaseModel):
    """The data that gets AES-encrypted and embedded in the JWT
    (Section 10c: "Token payload (AES-256 encrypted before signing)").
    """

    user_id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None
    role: str | None = None
    session_fingerprint: str
    issued_at: datetime
    expires_at: datetime
    token_type: str  # "access" | "refresh"
    jti: str
