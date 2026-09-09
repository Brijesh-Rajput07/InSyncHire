# LOCATION: services/migration_service/alembic_tenant/versions/20260601_0005_interview_sessions.py

"""add interview_sessions, interview_participants (M8 -- Interview Service)

Revision ID: 0005_interview_sessions
Revises: 0004_job_openings_and_applications
Create Date: 2026-06-01

Extends the SAME tenant Alembic chain Migration Service owns and runs on
every new tenant provisioning (per that suite's own env.py precedent --
"every future milestone adds its migration to this SAME chain -- do not
create a second tenant Alembic suite"). Existing tenants need this
applied via the system-admin `migrate-all-tenants` CLI command.

Columns for `interview_sessions` match Section 5 of the project plan
exactly, plus one deliberate addition -- a `tenant_id` column -- for the
same reason `0004_job_openings_and_applications` added one to
`job_openings`/`job_applications`: RLS policies need a real column to
compare against `current_setting('app.current_tenant_id')`, and every
other RLS'd table in this schema already carries one. Omitting it here
would make this table the only exception, silently reopening the
isolation gap the rest of the system is built to prevent.

`interview_participants` isn't in Section 5's top-level schema listing
either, but IS named explicitly in Section 5's own description
("interview_participants: session_id, user_id, role_in_session,
joined_at, left_at") -- same tenant_id addition applied here for the
identical RLS reason. A unique constraint on (session_id, user_id)
makes join idempotent at the DB layer (a second join attempt updates
the existing row rather than creating a duplicate -- see
`InterviewParticipantRepository.create_or_touch`).

`interviewer_ids` / `observer_ids` are stored as JSONB arrays of UUID
strings (not a join table) -- Section 5 lists them as `interviewer_ids[]`/
`observer_ids[]` directly on `interview_sessions`, and this milestone's
scope (scheduling + invite-sending only, no live room yet) has no need
for a richer per-interviewer relational model.

`room_token` is stored ENCRYPTED (Section 5: "room_token (encrypted)")
-- encryption happens at the application layer via
`interview_service.crypto.RoomTokenCrypto` before this column is
written, the same "encrypt in the app layer, plain TEXT column at rest"
pattern `tenants.db_connection_string` already established.

RLS follows the same pattern as every other tenant table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_interview_sessions"
down_revision: Union[str, None] = "0004_job_openings_and_applications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enable_rls(table_name: str) -> None:
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation_policy ON "{table_name}" '
        f"USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )


def upgrade() -> None:
    op.create_table(
        "interview_sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status", sa.String(30), nullable=False, server_default="SCHEDULED",
            comment="SCHEDULED | IN_PROGRESS | COMPLETED | CANCELLED",
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interviewer_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("observer_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("room_token", sa.Text(), nullable=True),
        sa.Column("recording_ref", sa.Text(), nullable=True),
        sa.Column("scheduled_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_interview_sessions_tenant_id", "interview_sessions", ["tenant_id"])
    op.create_index("ix_interview_sessions_job_id", "interview_sessions", ["job_id"])
    op.create_index("ix_interview_sessions_application_id", "interview_sessions", ["application_id"])
    op.create_index("ix_interview_sessions_candidate_user_id", "interview_sessions", ["candidate_user_id"])
    _enable_rls("interview_sessions")

    op.create_table(
        "interview_participants",
        sa.Column("participant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role_in_session", sa.String(30), nullable=False,
            comment="company_admin | recruiter | interviewer | observer | candidate",
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("session_id", "user_id", name="uq_interview_participants_session_user"),
    )
    op.create_index("ix_interview_participants_tenant_id", "interview_participants", ["tenant_id"])
    op.create_index("ix_interview_participants_session_id", "interview_participants", ["session_id"])
    _enable_rls("interview_participants")


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON "interview_participants"')
    op.drop_table("interview_participants")
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON "interview_sessions"')
    op.drop_table("interview_sessions")