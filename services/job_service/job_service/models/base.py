# LOCATION: services/job_service/job_service/models/base.py

"""Two declarative bases: one for the tenant-scoped tables this
service owns (job_openings, job_applications), one for the read-only
insynchire_global tables it needs (tenants -- to resolve/decrypt a
connection string and to iterate ACTIVE tenants for the public board;
global_users -- to check an authenticated caller's account_type, same
pattern as user_profile_service). Different physical databases must
never share one Base (Section 1)."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class TenantBase(DeclarativeBase):
    """Tables inside each tenant_<id>_db this service reads/writes."""


class GlobalBase(DeclarativeBase):
    """insynchire_global tables this service reads (never writes)."""