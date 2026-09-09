# LOCATION: services/user_profile_service/user_profile_service/services/application_submitted_consumer_service.py

"""
Consumes `application.submitted` (published by Job Service, M5) and
creates/touches the `user_applications_index` row -- the M5 half of
the pattern `user_registered_consumer_service.py` established in M4.
See `repositories/application_index_repository.py`'s docstring for why
Job Service doesn't write this table directly.
"""

from __future__ import annotations

import logging

from insynchire_events.schemas import ApplicationSubmittedEvent

from ..repositories import ApplicationIndexRepository

logger = logging.getLogger("user_profile_service.application_submitted_consumer")


class ApplicationSubmittedConsumerService:
    def __init__(self, *, users_db_session_factory):
        self._session_factory = users_db_session_factory

    async def handle_application_submitted(self, event: ApplicationSubmittedEvent) -> None:
        async with self._session_factory() as session:
            await ApplicationIndexRepository(session).create_or_touch(
                application_id=event.application_id, user_id=event.candidate_user_id,
                tenant_id=event.tenant_id, job_id=event.job_id,
            )
            await session.commit()

        logger.info(
            "indexed application_id=%s for candidate user_id=%s tenant_id=%s",
            event.application_id, event.candidate_user_id, event.tenant_id,
        )