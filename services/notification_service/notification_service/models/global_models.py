# LOCATION: services/notification_service/notification_service/models/global_models.py

"""
Read-only mirrors of `tenants` and `global_users` (insynchire_global) --
this service never writes either table. `Tenant` is used to look up a
tenant's display name (for email personalization) and to resolve/decrypt
its connection string (same TenantResolver pattern as tenant_service/
job_service). `GlobalUser` is used to resolve a `user_id` to an email
address for sending.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, Text
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
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)


class GlobalUser(GlobalBase):
    __tablename__ = "global_users"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)