# LOCATION: services/notification_service/notification_service/services/__init__.py

"""Business logic layer for the Notification Service."""

from .notification_dispatch_service import NotificationDispatchService

__all__ = ["NotificationDispatchService"]