# LOCATION: services/auth_service/auth_service/services/password_service.py

"""Password hashing/verification using bcrypt directly (no passlib —
avoids the extra dependency-resolution surface; bcrypt alone is
sufficient and is what passlib's bcrypt backend uses internally)."""

from __future__ import annotations

import bcrypt


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash (shouldn't happen for rows we wrote ourselves) -- treat as no match.
        return False
