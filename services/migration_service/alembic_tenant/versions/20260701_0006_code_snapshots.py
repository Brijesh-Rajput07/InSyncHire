# LOCATION: services/migration_service/alembic_tenant/versions/20260701_0006_code_snapshots.py

"""add code_snapshots (M9 -- Interview Service live room, code editor persistence)

Revision ID: 0006_code_snapshots
Revises: 0005_interview_sessions
Create Date: 2026-07-01

Extends the SAME tenant Alembic chain Migration Service owns and runs on
every new tenant provisioning. Existing tenants need this applied via
the system-admin `migrate-all-tenants` CLI command.

Columns match Section 5 of the project plan almost exactly:
`snapshot_id, session_id, content, language, diff_from_prev, timestamp,
triggered_analysis (bool), snapshot_index`, with two deliberate
deviations:

1. A `tenant_id` column, for the same RLS reason every prior milestone's
   new tenant table added one (`0004_job_openings_and_applications`,
   `0005_interview_sessions`) -- RLS policies need a real column to
   compare against `current_setting('app.current_tenant_id')`.
2. The plan's `timestamp` field is named `captured_at` here instead --
   every other table in this schema follows a `*_at` naming convention
   (`joined_at`, `applied_at`, `created_at`, `scheduled_at`, ...);
   `timestamp` would be the only exception. `captured_at` is the exact
   same data (when this snapshot was taken), just named consistently
   with the rest of the codebase.

RLS follows the same pattern as every other tenant table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006_code_snapshots"
down_revision: Union[str, None] = "0005_interview_sessions"
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
        "code_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(50), nullable=True),
        sa.Column("diff_from_prev", sa.Text(), nullable=True),
        sa.Column("snapshot_index", sa.Integer(), nullable=False),
        sa.Column("triggered_analysis", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_code_snapshots_tenant_id", "code_snapshots", ["tenant_id"])
    op.create_index("ix_code_snapshots_session_id", "code_snapshots", ["session_id"])
    _enable_rls("code_snapshots")


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON "code_snapshots"')
    op.drop_table("code_snapshots")