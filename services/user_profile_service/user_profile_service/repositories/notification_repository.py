# LOCATION: services/user_profile_service/user_profile_service/repositories/notification_repository.py

"""Repository for `user_notifications` (users_db) -- this service's
owned table (scaffolded in M4's Alembic chain, first actually written
here in M7). See `services/notification_record_consumer_service.py`'s
module docstring for why writes to this table live here rather than in
the new Notification Service."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import UserNotification


class NotificationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        type: str,
        title: str,
        body: str | None = None,
        action_url: str | None = None,
    ) -> UserNotification:
        notification = UserNotification(
            notification_id=uuid.uuid4(), user_id=user_id, type=type, title=title, body=body, action_url=action_url,
        )
        self._session.add(notification)
        await self._session.flush()
        return notification