# LOCATION: services/interview_service/interview_service/models/base.py

"""Two declarative bases: one for the tenant-scoped tables this service
owns (interview_sessions, interview_participants), one for the
read-only insynchire_global tables it needs (tenants -- to resolve/
decrypt a connection string; global_users -- to check an authenticated
caller's account_type, same pattern as job_service/user_profile_service).
Different physical databases must never share one Base (Section 1)."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class TenantBase(DeclarativeBase):
    """Tables inside each tenant_<id>_db this service reads/writes."""


class GlobalBase(DeclarativeBase):
    """insynchire_global tables this service reads (never writes)."""