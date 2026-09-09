# LOCATION: services/user_profile_service/user_profile_service/schemas/profile_schemas.py

"""Pydantic request/response schemas for /profile (Section 6: no
business logic in schemas -- pure shape validation)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    bio: str | None = None
    skills: list[str] | None = None
    experience_years: int | None = None
    current_title: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    availability: str | None = None
    updated_at: datetime


class UpdateProfileRequest(BaseModel):
    """All fields optional -- PUT /profile is a partial update; only
    fields explicitly present in the request body are changed (see
    `profile_service.update_profile`'s use of `exclude_unset=True`)."""

    bio: str | None = Field(default=None, max_length=2000)
    skills: list[str] | None = None
    experience_years: int | None = Field(default=None, ge=0, le=80)
    current_title: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    linkedin_url: str | None = Field(default=None, max_length=500)
    github_url: str | None = Field(default=None, max_length=500)
    portfolio_url: str | None = Field(default=None, max_length=500)
    availability: str | None = Field(default=None, max_length=50)