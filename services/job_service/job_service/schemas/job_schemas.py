# LOCATION: services/job_service/job_service/schemas/job_schemas.py

"""Pydantic request/response schemas for recruiter/company_admin job
posting CRUD (Section 6: pure shape validation, no business logic)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateJobRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    requirements: str | None = None
    skills_tags: list[str] = Field(default_factory=list)
    experience_level: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=255)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)


class UpdateJobRequest(BaseModel):
    """Partial update -- only fields explicitly present are applied
    (same `exclude_unset=True` convention as user_profile_service)."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    requirements: str | None = None
    skills_tags: list[str] | None = None
    experience_level: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=255)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    org_id: uuid.UUID
    title: str
    description: str
    requirements: str | None = None
    skills_tags: list[str]
    experience_level: str | None = None
    location: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    status: Literal["OPEN", "CLOSED"]
    posted_by: uuid.UUID
    created_at: datetime
    closed_at: datetime | None = None
    application_count: int