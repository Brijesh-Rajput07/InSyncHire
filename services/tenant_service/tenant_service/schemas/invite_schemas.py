# LOCATION: services/tenant_service/tenant_service/schemas/invite_schemas.py

"""Pydantic request/response schemas for the invite flow (Task F)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr

Role = Literal["recruiter", "interviewer", "observer"]
# Note: company_admin is deliberately NOT invitable here -- only assigned
# automatically to the tenant creator (Section: Tenant Onboarding Flow
# step 4). Promoting someone else to company_admin is a role-change
# operation, out of scope for the invite flow.


class InviteUserRequest(BaseModel):
    email: EmailStr
    role: Role


class InviteUserResponse(BaseModel):
    invite_id: uuid.UUID
    email: EmailStr
    role: str
    expires_at: datetime
    message: str = "Invite sent"


class AcceptInviteRequest(BaseModel):
    invite_token: str
    confirm_candidate_to_company_access: bool = False
    """FIX-M3: must be explicitly True if the accepting account is a
    `candidate` account_type -- see
    invite_acceptance_service.CandidateConfirmationRequiredError."""


class AcceptInviteResponse(BaseModel):
    membership_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    message: str = "Invite accepted"
