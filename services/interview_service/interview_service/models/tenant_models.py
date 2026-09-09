# LOCATION: services/interview_service/interview_service/models/tenant_models.py

"""
Models for `interview_sessions` / `interview_participants` (tenant DB,
migration `0005_interview_sessions`, M8) and `code_snapshots` (tenant
DB, migration `0006_code_snapshots`, M9). See each revision's docstring
for why every table here carries an explicit `tenant_id` column (RLS
requires one, even where Section 5's schema listing didn't spell it out
-- same precedent `0004_job_openings_and_applications` already
established for job_openings/job_applications).

`interviewer_ids`/`observer_ids` are stored as JSON lists of UUID
STRINGS (not native UUID objects) -- cross-dialect JSON columns can't
serialize `uuid.UUID` directly on SQLite (used in this repo's test
suites), so callers (repositories/services) are responsible for
`str(uuid)` on write and `uuid.UUID(...)` on read where a real UUID is
needed. This mirrors `job_openings.skills_tags`'s `list[str]` JSON
column precedent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import GUID

from .base import TenantBase


class InterviewSession(TenantBase):
    __tablename__ = "interview_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    application_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="SCHEDULED")
    # status values: SCHEDULED | IN_PROGRESS | COMPLETED | CANCELLED
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interviewer_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    observer_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    room_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ^ encrypted at the application layer (interview_service.crypto.RoomTokenCrypto)
    # before being written here -- never plaintext at rest, same pattern as
    # tenants.db_connection_string in insynchire_global.
    recording_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_by: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InterviewParticipant(TenantBase):
    __tablename__ = "interview_participants"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_interview_participants_session_user"),
    )

    participant_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    role_in_session: Mapped[str] = mapped_column(String(30), nullable=False)
    # role_in_session values: company_admin | recruiter | interviewer | observer | candidate
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CodeSnapshot(TenantBase):
    """M9: persisted history of the collaborative code editor's content
    during a live interview session (Section 5: 'code_snapshots: full
    history with diffs — enables playback'). Written by the WebSocket
    gateway's `code_update` message handler -- see `ws_gateway.py`.

    `captured_at` is this table's name for what Section 5 calls
    `timestamp` -- see migration `0006_code_snapshots`'s docstring for
    why."""

    __tablename__ = "code_snapshots"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    diff_from_prev: Mapped[strnnn  | None] = mapped_column(Text, nullable=True)
    snapshot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    triggered_analysis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())