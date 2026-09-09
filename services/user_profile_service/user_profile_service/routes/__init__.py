# LOCATION: services/user_profile_service/user_profile_service/routes/__init__.py

"""FastAPI routers for the User Profile Service."""

from .profile_routes import router as profile_router

__all__ = ["profile_router"]