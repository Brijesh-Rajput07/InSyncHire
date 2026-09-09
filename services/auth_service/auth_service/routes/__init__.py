# LOCATION: services/auth_service/auth_service/routes/__init__.py

"""FastAPI routers for the Auth Service."""

from .auth_routes import router as auth_router
from .signup_routes import router as signup_router

__all__ = ["auth_router", "signup_router"]
