# LOCATION: services/interview_service/interview_service/schemas/interview_schemas.py

"""Pydantic request/response schemas for the Interview Service (Section
6: pure shape validation, no business logic in schemas)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScheduleInterviewRequest(BaseModel):
    job_id: uuid.UUID
    application_id: uuid.UUID
    candidate_user_id: uuid.UUID
    interviewer_ids: list[uuid.UUID] = Field(..., min_length=1)
    observer_ids: list[uuid.UUID] = Field(default_factory=list)
    scheduled_at: datetime


class InterviewSessionResponse(BaseModel):
    """Deliberately omits `room_token` -- that value is only ever
    returned to an actual participant via `POST /interviews/{id}/join`
    (Section 10f: 'Short-lived session-scoped room tokens per
    participant'), never on a general schedule/read response that
    non-participant staff (e.g. company_admin browsing the interview
    list) might also see."""

    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    job_id: uuid.UUID
    application_id: uuid.UUID
    candidate_user_id: uuid.UUID
    status: Literal["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    scheduled_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    interviewer_ids: list[uuid.UUID]
    observer_ids: list[uuid.UUID]
    recording_ref: str | None = None
    scheduled_by: uuid.UUID
    created_at: datetime


class JoinInterviewResponse(BaseModel):
    session_id: uuid.UUID
    role_in_session: str
    room_token: str
    ws_connect_token: str
    joined_at: datetime
    message: str = "Joined interview session"