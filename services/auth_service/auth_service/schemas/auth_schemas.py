# LOCATION: services/auth_service/auth_service/schemas/auth_schemas.py

"""Pydantic schemas for login. TokenPayload itself moved to the shared
auth_tokens package during M3 -- re-exported here so existing imports
of `from auth_service.schemas import TokenPayload` keep working."""

from __future__ import annotations

import uuid

from auth_tokens import TokenPayload
from pydantic import BaseModel, EmailStr, Field

__all__ = ["LoginRequest", "LoginResponse", "TokenPayload"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    account_type: str
    message: str = "Logged in"
