# LOCATION: services/tenant_service/tenant_service/models/base.py

"""Two bases: one for the (read-mostly) insynchire_global tables this
service touches, one for the tenant-scoped tables it owns/writes."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class GlobalBase(DeclarativeBase):
    """insynchire_global tables this service reads."""


class TenantBase(DeclarativeBase):
    """Tables inside each tenant_<id>_db this service reads/writes."""
