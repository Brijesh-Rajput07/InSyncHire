# LOCATION: services/auth_service/auth_service/services/otp_service.py

"""
OTP generation/verification, Redis-backed (Section 10c):
  - 6-digit code, 10-minute TTL
  - Max 3 attempts, then the email is locked for 15 minutes
  - Only the OTP's hash is stored, never the plaintext code

`purpose` namespaces the OTP so the same email can have independent OTPs
in flight for different flows (e.g. "company_signup" vs "candidate_signup"
vs "login_2fa" if that's ever added) without colliding.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import string
from dataclasses import dataclass

from redis.asyncio import Redis

logger = logging.getLogger("auth_service.otp")


def _otp_key(email: str, purpose: str) -> str:
    return f"otp:{purpose}:{email.lower()}"


def _lockout_key(email: str, purpose: str) -> str:
    return f"otp_lockout:{purpose}:{email.lower()}"


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class OTPLockedError(Exception):
    def __init__(self, email: str):
        super().__init__(f"Too many failed OTP attempts for '{email}'. Try again later.")
        self.email = email


class OTPNotFoundOrExpiredError(Exception):
    def __init__(self, email: str):
        super().__init__(f"No active OTP found for '{email}' — it may have expired. Request a new one.")
        self.email = email


class OTPIncorrectError(Exception):
    def __init__(self, email: str, attempts_remaining: int):
        super().__init__(f"Incorrect OTP for '{email}'. {attempts_remaining} attempt(s) remaining.")
        self.email = email
        self.attempts_remaining = attempts_remaining


@dataclass
class OTPService:
    redis: Redis
    length: int = 6
    ttl_seconds: int = 10 * 60
    max_attempts: int = 3
    lockout_seconds: int = 15 * 60
    debug_log_otp: bool = False
    """DEV/TEST ONLY: if True, logs the plaintext OTP at INFO level when
    generated. Lets you exercise signup end-to-end before the
    Notification Service (M7) exists to actually email codes. NEVER
    enable this in a real deployment -- it defeats the point of the OTP
    by putting the code in application logs. Controlled by
    OTP_DEBUG_LOG_ENABLED in config.py, which defaults to False."""

    def _generate_code(self) -> str:
        return "".join(secrets.choice(string.digits) for _ in range(self.length))

    async def generate_and_store(self, email: str, purpose: str) -> str:
        """Generates a new OTP, stores its hash + a fresh attempt
        counter in Redis, and returns the PLAINTEXT code so the caller
        can email it. The plaintext is never itself stored."""
        if await self.redis.exists(_lockout_key(email, purpose)):
            raise OTPLockedError(email)

        code = self._generate_code()
        record = {"code_hash": _hash_code(code), "attempts": 0}
        await self.redis.set(_otp_key(email, purpose), json.dumps(record), ex=self.ttl_seconds)

        if self.debug_log_otp:
            logger.info("[DEV ONLY] OTP for %s (purpose=%s): %s", email, purpose, code)

        return code

    async def verify(self, email: str, purpose: str, submitted_code: str) -> None:
        """Raises on any failure; returns normally (None) on success and
        deletes the OTP record so it can't be replayed."""
        if await self.redis.exists(_lockout_key(email, purpose)):
            raise OTPLockedError(email)

        raw = await self.redis.get(_otp_key(email, purpose))
        if raw is None:
            raise OTPNotFoundOrExpiredError(email)

        record = json.loads(raw)
        if _hash_code(submitted_code) == record["code_hash"]:
            await self.redis.delete(_otp_key(email, purpose))
            return

        record["attempts"] += 1
        if record["attempts"] >= self.max_attempts:
            await self.redis.delete(_otp_key(email, purpose))
            await self.redis.set(_lockout_key(email, purpose), "1", ex=self.lockout_seconds)
            raise OTPLockedError(email)

        # Preserve remaining TTL rather than resetting it on a failed attempt
        remaining_ttl = await self.redis.ttl(_otp_key(email, purpose))
        await self.redis.set(
            _otp_key(email, purpose), json.dumps(record), ex=max(remaining_ttl, 1)
        )
        raise OTPIncorrectError(email, self.max_attempts - record["attempts"])
