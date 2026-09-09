# LOCATION: services/user_profile_service/user_profile_service/services/user_registered_consumer_service.py

"""
Consumes `user.registered` (published by Auth Service's candidate AND
company signup flows -- see FIX-M2, `candidate_signup_service.py` /
`company_signup_service.py`) and creates the `user_profiles` row.

This is the fix's whole point (RUN_GUIDE.md / Section 4 FIX-M2): Auth
Service used to write `users_db.user_profiles` directly and that write
was removed; THIS service, consuming the event Auth Service still
publishes, is now the one and only place that row gets created.

Only `account_type == "candidate"` gets a profile -- company_user
accounts (tenant staff) have no candidate-style profile/resume concept
(Section 1: profiles/resumes are part of the CANDIDATE Onboarding Flow
only). A redelivered event (Kafka at-least-once) is safe: ProfileRepository.
create_blank is idempotent.
"""

from __future__ import annotations

import logging

from insynchire_events.schemas import UserRegisteredEvent

from ..repositories import ProfileRepository

logger = logging.getLogger("user_profile_service.user_registered_consumer")


class UserRegisteredConsumerService:
    def __init__(self, *, users_db_session_factory):
        self._session_factory = users_db_session_factory

    async def handle_user_registered(self, event: UserRegisteredEvent) -> None:
        if event.account_type != "candidate":
            logger.info(
                "skipping profile creation for user_id=%s (account_type=%s, not a candidate)",
                event.user_id, event.account_type,
            )
            return

        async with self._session_factory() as session:
            await ProfileRepository(session).create_blank(event.user_id)
            await session.commit()

        logger.info("created user_profiles row for candidate user_id=%s", event.user_id)