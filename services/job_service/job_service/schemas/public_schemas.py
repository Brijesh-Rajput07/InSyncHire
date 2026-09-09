# LOCATION: services/job_service/job_service/schemas/public_schemas.py

"""Pydantic schema for the interim public job board -- see
services/public_board_service.py's docstring for the "interim" caveat.
Note `tenant_id` and `tenant_subdomain` are included in every listing:
the candidate-facing apply/my-application routes need to know which
tenant a job belongs to (candidates have no tenant context on their
token), and this response is how they find out (see routes/application_routes.py's
`X-Tenant-Id` header convention)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PublicJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_subdomain: str
    company_name: str
    title: str
    description: str
    skills_tags: list[str]
    experience_level: str | None = None
    location: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    application_count: int
    created_at: datetime