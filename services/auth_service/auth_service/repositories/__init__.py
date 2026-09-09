# LOCATION: services/auth_service/auth_service/repositories/__init__.py

"""Repository layer -- the only code that queries the DB directly."""

from .profile_repository import ProfileRepository
from .tenant_repository import DomainAlreadyRegisteredError, SubdomainTakenError, TenantRepository
from .user_repository import EmailAlreadyRegisteredError, UserRepository

__all__ = [
    "TenantRepository", "DomainAlreadyRegisteredError", "SubdomainTakenError",
    "UserRepository", "EmailAlreadyRegisteredError",
    "ProfileRepository",
]
