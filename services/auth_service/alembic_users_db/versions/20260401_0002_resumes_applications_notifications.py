# LOCATION: services/auth_service/alembic_users_db/versions/20260401_0002_resumes_applications_notifications.py

"""add user_resumes, user_applications_index, user_interview_history, user_notifications (M4)

Revision ID: 0002_resumes_applications_notifications
Revises: 0001_initial
Create Date: 2026-04-01

M4 extends the SAME users_db Alembic chain started by Auth Service in
M2 (0001_initial created `user_profiles`) -- per that migration's own
docstring: "M4 adds ... as NEW revisions in this SAME chain -- do not
create a second users_db migration suite."

Columns match Section 5 of the project plan exactly:
  - user_resumes
  - user_applications_index  (populated by Job Service, M5 -- table
    exists now so M5 doesn't need its own users_db migration suite)
  - user_interview_history   (populated by Interview Service, M8/M9 --
    same rationale)
  - user_notifications

No RLS on any of these -- users_db is not a per-tenant database
(Section 1); every table here is scoped by an explicit `user_id` filter
in the repository layer instead, same as `user_profiles` in 0001_initial
and every table in insynchire_global.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_resumes_applications_notifications"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_resumes",
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_url", sa.Text(), nullable=False),
        sa.Column("parsed_data", postgresql.JSONB(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_user_resumes_user_id", "user_resumes", ["user_id"])

    op.create_table(
        "user_applications_index",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("current_stage", sa.String(50), nullable=False, server_default="applied"),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_user_applications_index_user_id", "user_applications_index", ["user_id"])
    op.create_index("ix_user_applications_index_tenant_id", "user_applications_index", ["tenant_id"])

    op.create_table(
        "user_interview_history",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_in_session", sa.String(30), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_interview_history_user_id", "user_interview_history", ["user_id"])

    op.create_table(
        "user_notifications",
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_user_notifications_user_id", "user_notifications", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_notifications")
    op.drop_table("user_interview_history")
    op.drop_table("user_applications_index")
    op.drop_table("user_resumes")