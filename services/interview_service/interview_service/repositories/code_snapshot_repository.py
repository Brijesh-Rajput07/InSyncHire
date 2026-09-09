# LOCATION: services/interview_service/interview_service/repositories/code_snapshot_repository.py

"""Repository for `code_snapshots` (tenant DB, M9).

`create_next` is the only write path -- it looks up the highest
existing `snapshot_index` for the session and appends the next one,
so every WebSocket gateway call site doesn't have to compute the index
itself (Section 6: repository owns all query construction for its table).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CodeSnapshot


class CodeSnapshotRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def _next_index(self, session_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.max(CodeSnapshot.snapshot_index)).where(CodeSnapshot.session_id == session_id)
        )
        current_max = result.scalar()
        return 0 if current_max is None else current_max + 1

    async def create_next(
        self,
        *,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID,
        content: str,
        language: str | None,
        diff_from_prev: str | None,
        triggered_analysis: bool = False,
    ) -> CodeSnapshot:
        snapshot = CodeSnapshot(
            snapshot_id=uuid.uuid4(),
            tenant_id=tenant_id,
            session_id=session_id,
            content=content,
            language=language,
            diff_from_prev=diff_from_prev,
            snapshot_index=await self._next_index(session_id),
            triggered_analysis=triggered_analysis,
        )
        self._session.add(snapshot)
        await self._session.flush()
        return snapshot

    async def list_for_session(self, session_id: uuid.UUID) -> list[CodeSnapshot]:
        result = await self._session.execute(
            select(CodeSnapshot)
            .where(CodeSnapshot.session_id == session_id)
            .order_by(CodeSnapshot.snapshot_index.asc())
        )
        return list(result.scalars().all())

    async def get_latest(self, session_id: uuid.UUID) -> CodeSnapshot | None:
        result = await self._session.execute(
            select(CodeSnapshot)
            .where(CodeSnapshot.session_id == session_id)
            .order_by(CodeSnapshot.snapshot_index.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()