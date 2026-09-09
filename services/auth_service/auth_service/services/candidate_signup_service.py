# LOCATION: services/auth_service/auth_service/services/candidate_signup_service.py

"""
Candidate signup orchestration (Task D, Section: Candidate Onboarding
Flow — any email accepted, no domain restriction).

Two-step flow mirrors company signup: initiate() sends the OTP and
stashes pending signup details in Redis; complete() verifies the OTP,
creates the `global_users` row (account_type=candidate), publishes
`user.registered`, and issues the login token pair so the candidate is
immediately logged in after verifying.

FIX-M2: this used to ALSO write a blank row directly to
`users_db.user_profiles` here. That's wrong for two reasons: (1) Auth
Service should own identity only, not profile data (Section 1's
architecture), and (2) `users_db`'s schema is M4's milestone, not M2's
— Auth Service writing to a table it doesn't own via its own ad-hoc
model was sequencing the wrong way round. The fix: Auth Service now
ONLY publishes `user.registered`; a dedicated M4 service (consuming
this exact event) will be the ONE place that creates the
`user_profiles` row. Until M4 exists, a candidate simply has no
profile row yet — no code will break, User Profiles are just not
created by anything yet, which is the correct, honest state to be in
rather than a service reaching into a database that isn't its own.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from insynchire_events import Topics
from insynchire_events.schemas import UserRegisteredEvent
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories import UserRepository
from .otp_service import OTPService
from .password_service import hash_password
from .token_service import IssuedTokenPair, TokenService

_PURPOSE = "candidate_signup"
_PENDING_KEY_PREFIX = "pending_candidate_signup"


class CandidateSignupError(Exception):
    """Base class for candidate signup failures."""


class PendingSignupNotFoundError(CandidateSignupError):
    def __init__(self, email: str):
        super().__init__(f"No pending signup found for '{email}' — it may have expired. Start over.")
        self.email = email


@dataclass
class InitiateResult:
    email: str
    otp_expires_in_seconds: int


@dataclass
class CompleteResult:
    user_id: uuid.UUID
    email: str
    tokens: IssuedTokenPair


class CandidateSignupService:
    def __init__(
        self,
        *,
        redis: Redis,
        otp_service: OTPService,
        token_service: TokenService,
        publish,
    ):
        self._redis = redis
        self._otp_service = otp_service
        self._token_service = token_service
        self._publish = publish

    async def initiate(self, *, email: str, full_name: str, password: str) -> InitiateResult:
        pending = {
            "email": email.lower(),
            "full_name": full_name,
            "password_hash": hash_password(password),
        }
        await self._redis.set(
            f"{_PENDING_KEY_PREFIX}:{email.lower()}", json.dumps(pending), ex=self._otp_service.ttl_seconds
        )
        await self._otp_service.generate_and_store(email, _PURPOSE)

        return InitiateResult(email=email, otp_expires_in_seconds=self._otp_service.ttl_seconds)

    async def complete(
        self,
        *,
        global_session: AsyncSession,
        email: str,
        otp_code: str,
        fingerprint: str,
        trace_id: str,
    ) -> CompleteResult:
        await self._otp_service.verify(email, _PURPOSE, otp_code)

        raw_pending = await self._redis.get(f"{_PENDING_KEY_PREFIX}:{email.lower()}")
        if raw_pending is None:
            raise PendingSignupNotFoundError(email)
        pending = json.loads(raw_pending)
        await self._redis.delete(f"{_PENDING_KEY_PREFIX}:{email.lower()}")

        user_id = uuid.uuid4()

        user = await UserRepository(global_session).create_user(
            user_id=user_id,
            email=pending["email"],
            password_hash=pending["password_hash"],
            full_name=pending["full_name"],
            account_type="candidate",
            is_email_verified=True,
        )
        await global_session.commit()

        # FIX-M2: no direct users_db write here anymore -- see module
        # docstring. M4's service will consume this event and create
        # the user_profiles row itself.
        await self._publish(
            Topics.USER_REGISTERED.value,
            UserRegisteredEvent(trace_id=trace_id, user_id=user.user_id, email=user.email, account_type="candidate"),
        )

        tokens = await self._token_service.issue_token_pair(
            user_id=user.user_id, tenant_id=None, org_id=None, role=None, fingerprint=fingerprint
        )

        return CompleteResult(user_id=user.user_id, email=user.email, tokens=tokens)
