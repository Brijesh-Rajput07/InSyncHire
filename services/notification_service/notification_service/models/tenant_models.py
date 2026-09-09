# LOCATION: services/notification_service/notification_service/models/tenant_models.py

"""Read-only mirrors of tenant-DB tables -- this service reads them
ONLY to resolve notification recipients/content, never writes them
(Tenant Service owns `tenant_user_memberships`, Job Service owns
`job_openings`)."""

from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import GUID

from .base import TenantBase


class TenantUserMembership(TenantBase):
    __tablename__ = "tenant_user_memberships"

    membership_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)


class JobOpening(TenantBase):
    """Minimal mirror -- only the `title` column this service actually
    needs, same "minimal mirror" discipline used by every other
    service's read-only model (e.g. tenant_service's `GlobalUser`)."""

    __tablename__ = "job_openings"

    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)