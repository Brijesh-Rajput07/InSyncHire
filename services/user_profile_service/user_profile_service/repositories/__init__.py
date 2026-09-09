# LOCATION: services/user_profile_service/user_profile_service/repositories/__init__.py

"""Repository layer -- the only code that queries users_db / global_users directly."""

from .application_index_repository import ApplicationIndexRepository
from .global_user_repository import GlobalUserNotFoundError, GlobalUserRepository
from .notification_repository import NotificationRepository
from .profile_repository import ProfileRepository
from .resume_repository import ResumeRepository

__all__ = [
    "ProfileRepository", "ResumeRepository", "ApplicationIndexRepository",
    "GlobalUserRepository", "GlobalUserNotFoundError",
    "NotificationRepository",
]