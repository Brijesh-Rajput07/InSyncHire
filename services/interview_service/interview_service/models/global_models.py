# LOCATION: services/interview_service/interview_service/models/global_models.py

"""
Interview Service's read-only view of insynchire_global -- `tenants`
(to resolve/decrypt a connection string) and `global_users` (to check
an authenticated caller's account_type, same minimal-mirror pattern as
job_service/user_profile_service/tenant_service). This service never
writes either table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import GUID

from .base import GlobalBase


class Tenant(GlobalBase):
    __tablename__ = "tenants"

    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    subdomain: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    db_connection_string: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)


class GlobalUser(GlobalBase):
    __tablename__ = "global_users"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)