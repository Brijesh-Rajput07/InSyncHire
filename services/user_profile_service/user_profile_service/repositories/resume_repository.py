# LOCATION: services/user_profile_service/user_profile_service/repositories/resume_repository.py

"""Repository for `user_resumes` (users_db) -- this service's owned table."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import UserResume


class ResumeRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, resume_id: uuid.UUID) -> UserResume | None:
        result = await self._session.execute(select(UserResume).where(UserResume.resume_id == resume_id))
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserResume]:
        result = await self._session.execute(
            select(UserResume).where(UserResume.user_id == user_id).order_by(UserResume.uploaded_at.desc())
        )
        return list(result.scalars().all())

    async def unset_primary_for_user(self, user_id: uuid.UUID) -> None:
        """Clears is_primary on every OTHER resume for this user, so at
        most one resume is ever primary at a time (Section 5:
        `user_resumes.is_primary`)."""
        await self._session.execute(
            update(UserResume).where(UserResume.user_id == user_id).values(is_primary=False)
        )

    async def create(
        self, *, user_id: uuid.UUID, file_url: str, parsed_data: dict[str, Any] | None, is_primary: bool
    ) -> UserResume:
        if is_primary:
            await self.unset_primary_for_user(user_id)

        resume = UserResume(
            resume_id=uuid.uuid4(), user_id=user_id, file_url=file_url,
            parsed_data=parsed_data, is_primary=is_primary,
        )
        self._session.add(resume)
        await self._session.flush()
        return resume

    async def set_primary(self, resume: UserResume) -> UserResume:
        await self.unset_primary_for_user(resume.user_id)
        resume.is_primary = True
        await self._session.flush()
        return resume