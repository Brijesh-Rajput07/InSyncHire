# LOCATION: services/user_profile_service/user_profile_service/services/profile_service.py

"""
Candidate profile business logic (M4). All operations are scoped to the
authenticated caller's own `user_id` -- there is no "look up someone
else's profile" method here at all, by design (the route layer never
takes a user_id from the request body/path, only from the verified
token -- see routes/profile_routes.py).
"""

from __future__ import annotations

import uuid

from ..models import UserProfile
from ..repositories import ProfileRepository


class ProfileService:
    def __init__(self, *, users_db_session_factory):
        self._session_factory = users_db_session_factory

    async def get_profile(self, user_id: uuid.UUID) -> UserProfile:
        """Get-or-create: normally the profile already exists (created by
        UserRegisteredConsumerService the moment the candidate signed
        up), but if this request races that consumer (Kafka delivery is
        asynchronous), auto-vivify a blank one rather than 404ing on a
        legitimate candidate."""
        async with self._session_factory() as session:
            repo = ProfileRepository(session)
            profile = await repo.get_by_user_id(user_id)
            if profile is None:
                profile = await repo.create_blank(user_id)
                await session.commit()
            return profile

    async def update_profile(self, user_id: uuid.UUID, update_data: dict) -> UserProfile:
        """`update_data` should already be `.model_dump(exclude_unset=True)`
        from `UpdateProfileRequest` -- only keys explicitly present in
        the request are applied, so omitting a field leaves it
        unchanged (as opposed to `None` explicitly clearing it, which is
        also honored if the caller sends `"bio": null`)."""
        async with self._session_factory() as session:
            repo = ProfileRepository(session)
            profile = await repo.get_by_user_id(user_id)
            if profile is None:
                profile = await repo.create_blank(user_id)

            for field, value in update_data.items():
                setattr(profile, field, value)

            await session.commit()
            await session.refresh(profile)
            return profile