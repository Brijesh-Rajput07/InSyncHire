# LOCATION: services/user_profile_service/user_profile_service/models/__init__.py

"""SQLAlchemy models for the User Profile Service, split by physical database."""

from .base import GlobalBase, UsersDbBase
from .global_models import GlobalUser
from .users_db_models import (
    UserApplicationIndex,
    UserInterviewHistory,
    UserNotification,
    UserProfile,
    UserResume,
)

__all__ = [
    "UsersDbBase", "GlobalBase", "GlobalUser",
    "UserProfile", "UserResume", "UserApplicationIndex", "UserInterviewHistory", "UserNotification",
]