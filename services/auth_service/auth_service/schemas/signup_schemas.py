# LOCATION: services/auth_service/auth_service/schemas/signup_schemas.py

"""
Pydantic v2 request/response schemas for signup flows (Section 6: no
business logic in routes/schemas — these are pure shape validation).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator


class CompanySignupRequest(BaseModel):
    """Step 1 of company signup (Task C): submit corporate details,
    triggers domain validation + OTP send."""

    company_name: str = Field(..., min_length=1, max_length=255)
    subdomain: str = Field(..., min_length=2, max_length=63, pattern=r"^[a-z0-9](-?[a-z0-9])*$")
    company_email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=10)

    @field_validator("subdomain")
    @classmethod
    def _lowercase_subdomain(cls, v: str) -> str:
        return v.lower()


class CompanySignupInitiatedResponse(BaseModel):
    message: str = "OTP sent to company email"
    company_email: EmailStr
    otp_expires_in_seconds: int


class CompanySignupVerifyOTPRequest(BaseModel):
    company_email: EmailStr
    otp_code: str = Field(..., min_length=4, max_length=8)


class CompanySignupCompleteResponse(BaseModel):
    tenant_id: uuid.UUID
    subdomain: str
    status: str
    message: str = "Tenant created; provisioning in progress"


class CandidateSignupRequest(BaseModel):
    """Step 1 of candidate signup (Task D): any email accepted, no
    domain restriction (Section 1: "Candidate Onboarding Flow")."""

    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=10)


class CandidateSignupInitiatedResponse(BaseModel):
    message: str = "OTP sent to email"
    email: EmailStr
    otp_expires_in_seconds: int


class CandidateSignupVerifyOTPRequest(BaseModel):
    email: EmailStr
    otp_code: str = Field(..., min_length=4, max_length=8)


class CandidateSignupCompleteResponse(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    message: str = "Account created and logged in"
