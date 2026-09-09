# LOCATION: services/notification_service/notification_service/repositories/__init__.py

"""Read-only repository layer -- resolves recipients and email content.
This service writes to no database at all."""

from .global_tenant_repository import GlobalTenantRepository, TenantNotFoundError
from .global_user_repository import GlobalUserNotFoundError, GlobalUserRepository
from .job_opening_repository import JobOpeningRepository
from .membership_repository import MembershipRepository

__all__ = [
    "GlobalTenantRepository", "TenantNotFoundError",
    "GlobalUserRepository", "GlobalUserNotFoundError",
    "MembershipRepository",
    "JobOpeningRepository",
]