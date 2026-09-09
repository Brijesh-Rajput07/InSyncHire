# LOCATION: services/user_profile_service/user_profile_service/models/base.py

"""Two declarative bases: one for the users_db tables this service owns
and writes, one for the (read-only) insynchire_global tables it reads
purely to check an authenticated caller's account_type (Section 1:
different physical databases must never share one Base -- same pattern
used by tenant_service and auth_service)."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class UsersDbBase(DeclarativeBase):
    """Tables in users_db this service owns (user_profiles, user_resumes,
    user_applications_index, user_interview_history, user_notifications)."""


class GlobalBase(DeclarativeBase):
    """insynchire_global tables this service reads (global_users only,
    and only the account_type column -- see global_models.py)."""