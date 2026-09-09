# LOCATION: services/job_service/job_service/routes/__init__.py

"""FastAPI routers for the Job Service."""

from .application_routes import applications_router, jobs_router as application_jobs_router
from .job_routes import router as job_router
from .public_routes import router as public_router

__all__ = ["job_router", "application_jobs_router", "applications_router", "public_router"]