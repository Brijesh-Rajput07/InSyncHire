# LOCATION: services/tenant_service/tenant_service/models/tenant_models.py

"""
Models for tables inside each tenant_<id>_db. These tables were created
by Migration Service's Alembic suite (organizations,
tenant_user_memberships in 0001_initial; invited_users added by this
service in 0002_invited_users) — Tenant Service is simply the
application-layer owner of reading/writing them, same repository
pattern as everywhere else (Section 6).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import GUID

from .base import TenantBase


class Organization(TenantBase):
    __tablename__ = "organizations"

    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class TenantUserMembership(TenantBase):
    __tablename__ = "tenant_user_memberships"

    membership_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("organizations.org_id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # role values: company_admin | recruiter | interviewer | observer
    invited_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InvitedUser(TenantBase):
    __tablename__ = "invited_users"

    invite_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    invited_by: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
