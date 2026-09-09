# LOCATION: services/auth_service/auth_service/models/profile_models.py

"""
Minimal `user_profiles` model for `users_db`.

FIX-M2 UPDATE: Auth Service no longer connects to users_db at runtime
(see `services/candidate_signup_service.py`'s module docstring) — this
model is kept in place as a schema reference only, matching the table
the `alembic_users_db/` migration suite in this folder creates. M4's
dedicated service is what will actually import/extend this (or an
equivalent) once it owns users_db for real, consuming `user.registered`
to create the row instead of Auth Service writing it directly.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import GUID

from .base import UsersDbBase


class UserProfile(UsersDbBase):
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(GUID(), primary_key=True)
    bio: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    skills: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(50), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
