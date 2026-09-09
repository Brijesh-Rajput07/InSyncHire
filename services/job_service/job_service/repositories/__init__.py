# LOCATION: services/job_service/job_service/repositories/__init__.py

"""Repository layer -- the only code that queries tenant DB / insynchire_global tables directly."""

from .global_tenant_repository import GlobalTenantRepository, TenantNotFoundError
from .global_user_repository import GlobalUserNotFoundError, GlobalUserRepository
from .job_application_repository import JobApplicationRepository
from .job_opening_repository import JobOpeningRepository

__all__ = [
    "JobOpeningRepository", "JobApplicationRepository",
    "GlobalTenantRepository", "TenantNotFoundError",
    "GlobalUserRepository", "GlobalUserNotFoundError",
]