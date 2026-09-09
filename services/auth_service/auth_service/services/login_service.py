# LOCATION: services/auth_service/auth_service/services/login_service.py

"""
Login orchestration (Task D).

For `candidate` accounts this is a complete login. For `company_user`
accounts, this issues a token with tenant_id/org_id/role left unset —
selecting which tenant/org/role to act as (a user could in principle
belong to multiple tenants) is the Tenant Service's job (M3) via a
follow-up "select active tenant" step, out of scope for Auth Service.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import GlobalUser
from ..repositories import UserRepository
from .password_service import verify_password
from .token_service import IssuedTokenPair, TokenService


class LoginError(Exception):
    """Base class for login failures."""


class InvalidCredentialsError(LoginError):
    def __init__(self):
        super().__init__("Incorrect email or password")


class AccountInactiveError(LoginError):
    def __init__(self):
        super().__init__("This account has been deactivated")


@dataclass
class LoginResult:
    user: GlobalUser
    tokens: IssuedTokenPair


class LoginService:
    def __init__(self, *, token_service: TokenService):
        self._token_service = token_service

    async def login(
        self, *, session: AsyncSession, email: str, password: str, fingerprint: str
    ) -> LoginResult:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_email(email)

        # Deliberately identical error for "no such user" and "wrong
        # password" -- don't leak which emails are registered.
        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()

        if not user.is_active:
            raise AccountInactiveError()

        await user_repo.record_login(user.user_id)
        await session.commit()

        tokens = await self._token_service.issue_token_pair(
            user_id=user.user_id, tenant_id=None, org_id=None, role=None, fingerprint=fingerprint
        )

        return LoginResult(user=user, tokens=tokens)
