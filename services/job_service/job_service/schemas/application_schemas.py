# LOCATION: services/job_service/job_service/schemas/application_schemas.py

"""Pydantic schemas for candidate application submission + recruiter
applicant review."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class SubmitApplicationRequest(BaseModel):
    resume_id: uuid.UUID | None = None
    cover_note: str | None = None


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    application_id: uuid.UUID
    job_id: uuid.UUID
    candidate_user_id: uuid.UUID
    resume_id: uuid.UUID | None = None
    cover_note: str | None = None
    status: Literal["APPLIED", "ADVANCED", "REJECTED"]
    ai_rank: int | None = None
    ai_rank_evidence: dict[str, Any] | None = None
    applied_at: datetime
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None


class AdvanceOrRejectRequest(BaseModel):
    reason: str | None = None