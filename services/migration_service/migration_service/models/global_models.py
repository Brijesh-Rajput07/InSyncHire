# LOCATION: services/migration_service/migration_service/models/global_models.py

"""
SQLAlchemy models for `insynchire_global` — the control-plane database.

Matches Section 5 of the project plan exactly:
  - tenants
  - tenant_migrations
  - global_users
  - global_user_resumes

No RLS here (Section 1: "No RLS needed here — access is always via
authenticated service code with explicit scoping, not ad-hoc queries").

Note: `otp_store` is intentionally NOT modeled here — the plan specifies
it lives in Redis (TTL-based), not Postgres.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db import GUID

from .base import Base


class Tenant(Base):
    """One row per company/tenant. `db_connection_string` is stored
    encrypted (Section 2, Section 10b) — encryption happens in the
    repository layer via shared.db.crypto, never in the model itself."""

    __tablename__ = "tenants"

    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    subdomain: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    db_connection_string: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="trial")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    # status values: PENDING | ACTIVE | SUSPENDED | FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    migrations: Mapped[list["TenantMigration"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class TenantMigration(Base):
    """Tracks which Alembic revision each tenant DB is currently on.
    The Migration Service reads this to know what still needs to run
    (Section 1: "tenant_migrations table: tracks which Alembic migration
    version each tenant DB is on")."""

    __tablename__ = "tenant_migrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False, index=True
    )
    alembic_version: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    applied_by_service: Mapped[str] = mapped_column(String(100), nullable=False, default="migration_service")

    tenant: Mapped["Tenant"] = relationship(back_populates="migrations")


class GlobalUser(Base):
    """Every user identity in the system — candidates AND company users
    alike (Section 1: "global_users table: ALL user identities live
    here"). Core identity only; no tenant-specific data."""

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

    resumes: Mapped[list["GlobalUserResume"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class GlobalUserResume(Base):
    """Resume files/parsed data linked to a user_id — lives in the
    global DB (not a tenant DB) so it follows the candidate across
    every company they apply to (Section 1)."""

    __tablename__ = "global_user_resumes"

    resume_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("global_users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["GlobalUser"] = relationship(back_populates="resumes")
