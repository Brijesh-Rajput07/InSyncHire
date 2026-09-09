# LOCATION: services/interview_service/interview_service/routes/__init__.py

"""FastAPI routers for the Interview Service."""

from .interview_routes import router as interview_router

__all__ = ["interview_router"]