# LOCATION: services/interview_service/interview_service/repositories/interview_session_repository.py

"""Repository for `interview_sessions` (tenant DB)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import InterviewSession


class InterviewSessionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, session_id: uuid.UUID) -> InterviewSession | None:
        result = await self._session.execute(
            select(InterviewSession).where(InterviewSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        application_id: uuid.UUID,
        candidate_user_id: uuid.UUID,
        interviewer_ids: list[uuid.UUID],
        observer_ids: list[uuid.UUID],
        scheduled_at: datetime,
        scheduled_by: uuid.UUID,
        room_token: str | None,
    ) -> InterviewSession:
        session_row = InterviewSession(
            session_id=uuid.uuid4(),
            tenant_id=tenant_id,
            job_id=job_id,
            application_id=application_id,
            candidate_user_id=candidate_user_id,
            status="SCHEDULED",
            scheduled_at=scheduled_at,
            interviewer_ids=[str(i) for i in interviewer_ids],
            observer_ids=[str(o) for o in observer_ids],
            room_token=room_token,
            scheduled_by=scheduled_by,
        )
        self._session.add(session_row)
        await self._session.flush()
        return session_row

    async def list_for_candidate(self, candidate_user_id: uuid.UUID) -> list[InterviewSession]:
        """Not wired to any route yet in M8 (no candidate 'my interviews'
        list endpoint requested) -- provided now since the repository is
        the only place that should ever query this table, so a future
        endpoint doesn't need to add raw SQL elsewhere (Section 6)."""
        result = await self._session.execute(
            select(InterviewSession)
            .where(InterviewSession.candidate_user_id == candidate_user_id)
            .order_by(InterviewSession.scheduled_at.desc())
        )
        return list(result.scalars().all())