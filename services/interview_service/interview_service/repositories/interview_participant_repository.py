# LOCATION: services/interview_service/interview_service/repositories/interview_participant_repository.py

"""Repository for `interview_participants` (tenant DB).

`create_or_touch` is the join-idempotency primitive: joining the same
session twice (a page refresh, a flaky connection reconnecting) must
never raise or create a duplicate row -- the DB's own
`uq_interview_participants_session_user` constraint (migration
`0005_interview_sessions`) is the second, independent enforcement layer
underneath this, same "two independent layers" discipline used
everywhere else in this codebase (RLS + repository-level tenant
scoping, `MembershipRepository.create`'s pre-check + DB unique
constraint, etc.).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import InterviewParticipant


class InterviewParticipantRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_session_and_user(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> InterviewParticipant | None:
        result = await self._session.execute(
            select(InterviewParticipant).where(
                InterviewParticipant.session_id == session_id,
                InterviewParticipant.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_session(self, session_id: uuid.UUID) -> list[InterviewParticipant]:
        result = await self._session.execute(
            select(InterviewParticipant).where(InterviewParticipant.session_id == session_id)
        )
        return list(result.scalars().all())

    async def create_or_touch(
        self,
        *,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        role_in_session: str,
    ) -> InterviewParticipant:
        existing = await self.get_by_session_and_user(session_id, user_id)
        if existing is not None:
            # A rejoin (e.g. reconnecting) clears any prior left_at --
            # first-ever joined_at is preserved, not reset.
            if existing.left_at is not None:
                existing.left_at = None
            await self._session.flush()
            return existing

        participant = InterviewParticipant(
            participant_id=uuid.uuid4(),
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_id,
            role_in_session=role_in_session,
        )
        self._session.add(participant)
        await self._session.flush()
        return participant

    async def mark_left(self, participant: InterviewParticipant) -> InterviewParticipant:
        participant.left_at = datetime.now(timezone.utc)
        await self._session.flush()
        return participant