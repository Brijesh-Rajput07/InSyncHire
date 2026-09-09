# LOCATION: shared/shared-db/shared/db/crypto.py

"""
Symmetric encryption for values that must never sit in the DB as
plaintext — specifically `tenants.db_connection_string` (Section 2:
"db_connection_string (encrypted)").

Uses Fernet (AES-128-CBC + HMAC via the `cryptography` package). The key
comes from an env var / secrets manager only — never hardcoded, never
committed (Section 10i).
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class ConnectionStringCrypto:
    """Wraps a Fernet key for encrypting/decrypting DB connection strings."""

    def __init__(self, key: str | None = None):
        key = key or os.getenv("CONNECTION_STRING_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError(
                "CONNECTION_STRING_ENCRYPTION_KEY is not set. Generate one with "
                "`python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"` and store it in your "
                "secrets manager / .env — never commit it."
            )
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext_dsn: str) -> str:
        return self._fernet.encrypt(plaintext_dsn.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext_dsn: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext_dsn.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "Failed to decrypt connection string — wrong key or corrupted value"
            ) from exc


_default_crypto: ConnectionStringCrypto | None = None


def get_crypto() -> ConnectionStringCrypto:
    global _default_crypto
    if _default_crypto is None:
        _default_crypto = ConnectionStringCrypto()
    return _default_crypto
