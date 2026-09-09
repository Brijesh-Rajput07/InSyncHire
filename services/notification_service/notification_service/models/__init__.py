# LOCATION: services/notification_service/notification_service/models/__init__.py

"""Read-only SQLAlchemy models for the Notification Service, split by
physical database. This service owns and writes to neither."""

from .base import GlobalBase, TenantBase
from .global_models import GlobalUser, Tenant
from .tenant_models import JobOpening, TenantUserMembership

__all__ = ["GlobalBase", "TenantBase", "Tenant", "GlobalUser", "TenantUserMembership", "JobOpening"]