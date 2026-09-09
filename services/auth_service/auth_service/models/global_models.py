# LOCATION: services/auth_service/auth_service/models/global_models.py

"""
Auth Service's own SQLAlchemy models for the `insynchire_global` tables
it reads/writes: `tenants` and `global_users`.

These mirror the same physical tables owned/migrated by the Migration
Service (M1) — every microservice in this architecture defines its own
models against shared tables it needs (repository pattern, Section 6);
schema changes still only ever happen via migration_service's Alembic
suite, never auto-created here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import GUID

from .base import GlobalBase


class Tenant(GlobalBase):
    __tablename__ = "tenants"

    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    subdomain: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    db_connection_string: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="trial")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)


class GlobalUser(GlobalBase):
    __tablename__ = "global_users"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # account_type values: candidate | company_user
