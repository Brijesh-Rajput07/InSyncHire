# LOCATION: services/auth_service/auth_service/schemas/__init__.py

"""Pydantic request/response schemas for the Auth Service."""

from .auth_schemas import LoginRequest, LoginResponse, TokenPayload
from .signup_schemas import (
    CandidateSignupCompleteResponse,
    CandidateSignupInitiatedResponse,
    CandidateSignupRequest,
    CandidateSignupVerifyOTPRequest,
    CompanySignupCompleteResponse,
    CompanySignupInitiatedResponse,
    CompanySignupRequest,
    CompanySignupVerifyOTPRequest,
)

__all__ = [
    "LoginRequest", "LoginResponse", "TokenPayload",
    "CompanySignupRequest", "CompanySignupInitiatedResponse",
    "CompanySignupVerifyOTPRequest", "CompanySignupCompleteResponse",
    "CandidateSignupRequest", "CandidateSignupInitiatedResponse",
    "CandidateSignupVerifyOTPRequest", "CandidateSignupCompleteResponse",
]
