# LOCATION: services/user_profile_service/user_profile_service/models/users_db_models.py

"""
SQLAlchemy models for users_db (Section 5). Matches the tables created
by `services/auth_service/alembic_users_db/versions/0001_initial.py`
(user_profiles) and `.../0002_resumes_applications_notifications.py`
(everything else, added by this milestone -- M4).

Repository pattern (Section 6): this is the ONLY service that owns
writes to user_profiles/user_resumes as of M4. user_applications_index
and user_interview_history exist here as read/query models for future
milestones (Job Service = M5, Interview Service = M8/M9) that will do
the actual writing once they exist -- this service does not populate
them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import GUID

from .base import UsersDbBase


class UserProfile(UsersDbBase):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    bio: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    skills: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    experience_years: Mapped[int | None] = mapped_column(nullable=True)
    current_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(50), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserResume(UsersDbBase):
    __tablename__ = "user_resumes"

    resume_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserApplicationIndex(UsersDbBase):
    """Populated by Job Service (M5) on application.submitted -- this
    service only defines/reads the model so M5 doesn't need a second
    users_db migration suite."""

    __tablename__ = "user_applications_index"

    application_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    current_stage: Mapped[str] = mapped_column(String(50), nullable=False, default="applied")
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserInterviewHistory(UsersDbBase):
    """Populated by Interview Service (M8/M9) -- same rationale as
    UserApplicationIndex above."""

    __tablename__ = "user_interview_history"

    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    role_in_session: Mapped[str] = mapped_column(String(30), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserNotification(UsersDbBase):
    """Platform-level notifications not tied to one tenant (Section 5).
    Populated by Notification Service (M7) once it exists -- this
    service defines the model/schema now so that milestone doesn't need
    its own users_db migration suite either."""

    __tablename__ = "user_notifications"

    notification_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())