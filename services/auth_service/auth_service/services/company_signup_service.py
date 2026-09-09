# LOCATION: services/auth_service/auth_service/services/company_signup_service.py

"""
Company signup orchestration (Task C, Section: Tenant Onboarding Flow
step 1).

Two-step flow:
  1. initiate() -- validates the corporate domain, generates an OTP,
     and stashes the pending signup details (not yet a real user/tenant
     row) in Redis keyed by email, so nothing is written to Postgres
     until the OTP is actually verified.
  2. complete() -- verifies the OTP, creates the `global_users` row
     (account_type=company_user), creates the `tenants` row with
     status=PENDING, and publishes `tenant.signup_initiated` to Kafka
     so the Migration Service (M1) picks it up and provisions the
     tenant DB.

Note: assigning the first user as `company_admin` in
`tenant_user_memberships` happens in the Tenant Service (M3), triggered
by consuming `tenant.created` once Migration Service finishes
provisioning — it can't happen here because the tenant DB doesn't
exist yet at signup time.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from insynchire_events import Topics
from insynchire_events.schemas import TenantSignupInitiatedEvent, UserRegisteredEvent
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories import TenantRepository, UserRepository
from .domain_validation_service import DomainValidationService, extract_domain
from .otp_service import OTPService
from .password_service import hash_password

_PURPOSE = "company_signup"
_PENDING_KEY_PREFIX = "pending_company_signup"


class CompanySignupError(Exception):
    """Base class for company signup failures."""


class PendingSignupNotFoundError(CompanySignupError):
    def __init__(self, email: str):
        super().__init__(f"No pending signup found for '{email}' — it may have expired. Start over.")
        self.email = email


@dataclass
class InitiateResult:
    company_email: str
    otp_expires_in_seconds: int


@dataclass
class CompleteResult:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    subdomain: str
    status: str


class CompanySignupService:
    def __init__(
        self,
        *,
        redis: Redis,
        otp_service: OTPService,
        domain_validator: DomainValidationService,
        publish,  # Callable[[str, BaseEvent], Awaitable[None]] from insynchire_events
    ):
        self._redis = redis
        self._otp_service = otp_service
        self._domain_validator = domain_validator
        self._publish = publish

    async def initiate(
        self, *, company_name: str, subdomain: str, company_email: str, full_name: str, password: str
    ) -> InitiateResult:
        # Raises PublicEmailDomainError / DomainHasNoMailServerError on failure
        self._domain_validator.validate(company_email)

        pending = {
            "company_name": company_name,
            "subdomain": subdomain.lower(),
            "company_email": company_email.lower(),
            "full_name": full_name,
            "password_hash": hash_password(password),
        }
        await self._redis.set(
            f"{_PENDING_KEY_PREFIX}:{company_email.lower()}",
            json.dumps(pending),
            ex=self._otp_service.ttl_seconds,
        )
        await self._otp_service.generate_and_store(company_email, _PURPOSE)

        return InitiateResult(
            company_email=company_email, otp_expires_in_seconds=self._otp_service.ttl_seconds
        )

    async def complete(
        self, *, session: AsyncSession, company_email: str, otp_code: str, trace_id: str
    ) -> CompleteResult:
        # Raises OTPLockedError / OTPNotFoundOrExpiredError / OTPIncorrectError on failure
        await self._otp_service.verify(company_email, _PURPOSE, otp_code)

        raw_pending = await self._redis.get(f"{_PENDING_KEY_PREFIX}:{company_email.lower()}")
        if raw_pending is None:
            raise PendingSignupNotFoundError(company_email)
        pending = json.loads(raw_pending)
        await self._redis.delete(f"{_PENDING_KEY_PREFIX}:{company_email.lower()}")

        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        user_repo = UserRepository(session)
        tenant_repo = TenantRepository(session)

        user = await user_repo.create_user(
            user_id=user_id,
            email=pending["company_email"],
            password_hash=pending["password_hash"],
            full_name=pending["full_name"],
            account_type="company_user",
            is_email_verified=True,
        )
        tenant = await tenant_repo.create_pending(
            tenant_id=tenant_id,
            subdomain=pending["subdomain"],
            company_name=pending["company_name"],
            company_domain=extract_domain(pending["company_email"]),
            created_by_user_id=user_id,
        )
        await session.commit()

        await self._publish(
            Topics.USER_REGISTERED.value,
            UserRegisteredEvent(trace_id=trace_id, user_id=user.user_id, email=user.email, account_type="company_user"),
        )
        await self._publish(
            Topics.TENANT_SIGNUP_INITIATED.value,
            TenantSignupInitiatedEvent(
                trace_id=trace_id,
                tenant_id=tenant.tenant_id,
                subdomain=tenant.subdomain,
                company_name=tenant.company_name,
                company_domain=tenant.company_domain,
                created_by_user_id=user_id,
            ),
        )

        return CompleteResult(
            tenant_id=tenant.tenant_id, user_id=user.user_id, subdomain=tenant.subdomain, status=tenant.status
        )
