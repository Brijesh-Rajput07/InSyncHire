# LOCATION: services/interview_service/interview_service/crypto.py

"""
Room token encryption (Section 5: `interview_sessions.room_token
(encrypted)`; Section: STAGE 5 -- INTERVIEW SCHEDULING -- "Short-lived
session-scoped room tokens per participant" and Section 10f).

A dedicated Fernet-keyed wrapper, deliberately NOT reusing
`shared.db.crypto.ConnectionStringCrypto`'s key -- that key protects
tenant DB connection strings specifically (Section 10b), a different
secret with a different blast radius than a room token (a leaked room
token lets someone join a live interview room; a leaked DB connection
string lets someone connect to a tenant's entire database). Two
different secrets get two different keys, even though the underlying
Fernet mechanics are identical -- the same reasoning
`shared/auth-tokens` and `shared/shared-db` already apply to keeping
`TOKEN_PAYLOAD_ENCRYPTION_KEY` and `CONNECTION_STRING_ENCRYPTION_KEY`
separate system secrets.

Note: this milestone (M8) only stores/decrypts the room token -- it does
not yet mint a real LiveKit/Daily/Twilio room or a short-lived signed
WebSocket connection token (Section 10f: "Managed SFU SDK ... Short-lived
session-scoped room tokens per participant"). The plaintext value
generated here is an opaque room identifier a future milestone (M9, the
live WebSocket gateway) will use to look up/join the actual room --
swapping in a real SFU-issued token later does not change this module's
interface (still `encrypt`/`decrypt` a string).
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class RoomTokenCrypto:
    """Wraps a Fernet key for encrypting/decrypting `interview_sessions.room_token`."""

    def __init__(self, key: str | None = None):
        key = key or os.getenv("ROOM_TOKEN_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError(
                "ROOM_TOKEN_ENCRYPTION_KEY is not set. Generate one with "
                "`python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"` and store it in your "
                "secrets manager / .env — never commit it."
            )
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext_token: str) -> str:
        return self._fernet.encrypt(plaintext_token.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext_token: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext_token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "Failed to decrypt room token — wrong key or corrupted value"
            ) from exc