# LOCATION: services/tenant_service/tenant_service/routes/__init__.py

"""FastAPI routers for the Tenant Service."""

from .invite_routes import router as invite_router
from .selection_routes import router as selection_router

__all__ = ["invite_router", "selection_router"]
