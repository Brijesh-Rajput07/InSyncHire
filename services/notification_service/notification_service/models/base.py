# LOCATION: services/notification_service/notification_service/models/base.py

"""Two declarative bases: one for the (read-only) insynchire_global
tables this service reads to resolve recipients, one for the
(read-only) tenant-DB tables it reads to resolve org-side recipients
(recruiters/company_admins) for application.submitted/scorecard.generated.
This service owns and writes NEITHER database -- see config.py's
module docstring."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class GlobalBase(DeclarativeBase):
    """insynchire_global tables this service reads (never writes)."""


class TenantBase(DeclarativeBase):
    """Tables inside each tenant_<id>_db this service reads (never writes)."""