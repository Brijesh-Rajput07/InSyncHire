# LOCATION: services/auth_service/auth_service/services/__init__.py

"""Business logic layer for the Auth Service."""

from .candidate_signup_service import CandidateSignupError, CandidateSignupService, PendingSignupNotFoundError as CandidatePendingSignupNotFoundError
from .company_signup_service import CompanySignupError, CompanySignupService, PendingSignupNotFoundError as CompanyPendingSignupNotFoundError
from .domain_validation_service import (
    DomainHasNoMailServerError,
    DomainValidationError,
    DomainValidationService,
    PublicEmailDomainError,
)
from .login_service import AccountInactiveError, InvalidCredentialsError, LoginError, LoginService
from .otp_service import OTPIncorrectError, OTPLockedError, OTPNotFoundOrExpiredError, OTPService
from .password_service import hash_password, verify_password
from .token_service import (
    IssuedTokenPair,
    TokenError,
    TokenExpiredError,
    TokenFingerprintMismatchError,
    TokenInvalidError,
    TokenRevokedError,
    TokenService,
    generate_rsa_keypair_pem,
    session_fingerprint,
)

__all__ = [
    "CompanySignupService", "CompanySignupError", "CompanyPendingSignupNotFoundError",
    "CandidateSignupService", "CandidateSignupError", "CandidatePendingSignupNotFoundError",
    "DomainValidationService", "DomainValidationError", "PublicEmailDomainError", "DomainHasNoMailServerError",
    "OTPService", "OTPLockedError", "OTPNotFoundOrExpiredError", "OTPIncorrectError",
    "hash_password", "verify_password",
    "TokenService", "IssuedTokenPair", "TokenError", "TokenExpiredError", "TokenInvalidError",
    "TokenRevokedError", "TokenFingerprintMismatchError", "generate_rsa_keypair_pem", "session_fingerprint",
    "LoginService", "LoginError", "InvalidCredentialsError", "AccountInactiveError",
]
