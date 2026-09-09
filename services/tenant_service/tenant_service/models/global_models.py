# LOCATION: services/tenant_service/tenant_service/models/global_models.py

"""
Tenant Service's own view of `tenants` and `global_users` (both in
insynchire_global) — it only ever READS these tables, never writes
them.
  - `tenants`: to resolve a tenant's connection string and confirm it's
    ACTIVE. Writing tenants is Auth Service's (create PENDING) and
    Migration Service's (activate) job.
  - `global_users`: FIX-M3 addition — to check an invite-accepter's
    `account_type` (see invite_acceptance_service.py's confirmation
    flow for a candidate-turned-company-user). Writing global_users is
    entirely Auth Service's job.
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
    """Read-only mirror of the columns Tenant Service actually needs
    (account_type) -- NOT the full model Auth Service owns. Adding
    columns here that Tenant Service doesn't use would misleadingly
    suggest it has a reason to read them."""

    __tablename__ = "global_users"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
