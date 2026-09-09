# LOCATION: services/user_profile_service/user_profile_service/services/resume_service.py

"""Candidate resume business logic (M4) -- same ownership-scoping
discipline as ProfileService: every method takes the authenticated
caller's own user_id, and select_primary_resume additionally verifies
the target resume actually belongs to that user before touching it
(ResumeOwnershipError) -- a candidate must never be able to flip
`is_primary` on someone else's resume by guessing a resume_id."""

from __future__ import annotations

import uuid
from typing import Any

from ..models import UserResume
from ..repositories import ResumeRepository


class ResumeError(Exception):
    """Base class for resume operation failures."""


class ResumeNotFoundError(ResumeError):
    def __init__(self, resume_id: uuid.UUID):
        super().__init__(f"Resume {resume_id} not found")


class ResumeOwnershipError(ResumeError):
    def __init__(self):
        super().__init__("This resume does not belong to the authenticated user")


class ResumeService:
    def __init__(self, *, users_db_session_factory):
        self._session_factory = users_db_session_factory

    async def upload_resume(
        self, *, user_id: uuid.UUID, file_url: str, parsed_data: dict[str, Any] | None, is_primary: bool
    ) -> UserResume:
        async with self._session_factory() as session:
            resume = await ResumeRepository(session).create(
                user_id=user_id, file_url=file_url, parsed_data=parsed_data, is_primary=is_primary
            )
            await session.commit()
            await session.refresh(resume)
            return resume

    async def list_resumes(self, user_id: uuid.UUID) -> list[UserResume]:
        async with self._session_factory() as session:
            return await ResumeRepository(session).list_for_user(user_id)

    async def select_primary_resume(self, *, user_id: uuid.UUID, resume_id: uuid.UUID) -> UserResume:
        async with self._session_factory() as session:
            repo = ResumeRepository(session)
            resume = await repo.get_by_id(resume_id)
            if resume is None:
                raise ResumeNotFoundError(resume_id)
            if resume.user_id != user_id:
                raise ResumeOwnershipError()

            resume = await repo.set_primary(resume)
            await session.commit()
            await session.refresh(resume)
            return resume