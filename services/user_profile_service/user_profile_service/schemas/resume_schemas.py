# LOCATION: services/user_profile_service/user_profile_service/schemas/resume_schemas.py

"""Pydantic request/response schemas for /profile/resume.

Note: actual file upload/storage (multipart, S3/GCS, resume parsing) is
out of scope for M4 -- this milestone's job is the users_db schema +
ownership-scoped CRUD over resume METADATA. `file_url` is accepted as
already-uploaded-elsewhere (e.g. a pre-signed URL from a future file
storage integration); `parsed_data` likewise is accepted as
already-parsed-elsewhere (e.g. a future resume-parsing agent's output),
not parsed by this service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class UploadResumeRequest(BaseModel):
    file_url: str
    parsed_data: dict[str, Any] | None = None
    is_primary: bool = False


class ResumeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resume_id: uuid.UUID
    user_id: uuid.UUID
    file_url: str
    parsed_data: dict[str, Any] | None = None
    is_primary: bool
    uploaded_at: datetime


class SelectPrimaryResumeRequest(BaseModel):
    resume_id: uuid.UUID