# LOCATION: services/job_service/job_service/models/tenant_models.py

"""
Models for `job_openings` / `job_applications` (tenant DB), created by
the Migration Service's tenant Alembic chain, revision
`0004_job_openings_and_applications` (M5). See that revision's
docstring for why both tables carry an explicit `tenant_id` column
(RLS requires one, even though Section 5's schema listing omitted it).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import GUID

from .base import TenantBase


class JobOpening(TenantBase):
    __tablename__ = "job_openings"

    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    experience_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", index=True)
    # status values: OPEN | CLOSED
    posted_by: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    application_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class JobApplication(TenantBase):
    __tablename__ = "job_applications"
    __table_args__ = (UniqueConstraint("job_id", "candidate_user_id", name="uq_job_applications_job_candidate"),)

    application_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    cover_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="APPLIED")
    # status values: APPLIED | ADVANCED | REJECTED
    ai_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_rank_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)