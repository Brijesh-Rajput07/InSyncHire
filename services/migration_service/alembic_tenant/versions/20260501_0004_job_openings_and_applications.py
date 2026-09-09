# LOCATION: services/migration_service/alembic_tenant/versions/20260501_0004_job_openings_and_applications.py

"""add job_openings, job_applications (M5 -- Job Service)

Revision ID: 0004_job_openings_and_applications
Revises: 0003_agent_and_process_logs
Create Date: 2026-05-01

Extends the SAME tenant Alembic chain Migration Service owns and runs
on every new tenant provisioning (per that suite's own env.py: "every
future milestone adds its migration to this SAME chain -- do not
create a second tenant Alembic suite"). Existing tenants need this
applied via the system-admin `migrate-all-tenants` CLI command.

Columns for `job_openings` / `job_applications` match Section 5 of the
project plan, with one deliberate addition: a `tenant_id` column on
both tables. Section 5's own listing omits it, but EVERY other RLS'd
tenant table in this codebase (organizations, invited_users,
agent_decision_logs, agent_guardrail_logs, process_logs) carries an
explicit `tenant_id` column because Postgres RLS policies need a real
column to compare against `current_setting('app.current_tenant_id')`
-- there is no way to enable RLS without one. Omitting it here would
make these two tables the only ones in the entire schema without RLS,
silently reopening the isolation gap the rest of the system is built
to prevent (Section 10b: "PostgreSQL RLS ... engine-level isolation
survives app bugs"). Keeping the column is consistent with precedent,
not a deviation from it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_job_openings_and_applications"
down_revision: Union[str, None] = "0003_agent_and_process_logs"
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
        "job_openings",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("requirements", sa.Text(), nullable=True),
        sa.Column("skills_tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("experience_level", sa.String(50), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="OPEN",
            comment="OPEN | CLOSED",
        ),
        sa.Column("posted_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_job_openings_tenant_id", "job_openings", ["tenant_id"])
    op.create_index("ix_job_openings_org_id", "job_openings", ["org_id"])
    op.create_index("ix_job_openings_status", "job_openings", ["status"])
    _enable_rls("job_openings")

    op.create_table(
        "job_applications",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cover_note", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(30), nullable=False, server_default="APPLIED",
            comment="APPLIED | ADVANCED | REJECTED",
        ),
        sa.Column("ai_rank", sa.Integer(), nullable=True),
        sa.Column("ai_rank_evidence", postgresql.JSONB(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_job_applications_tenant_id", "job_applications", ["tenant_id"])
    op.create_index("ix_job_applications_job_id", "job_applications", ["job_id"])
    op.create_index("ix_job_applications_candidate_user_id", "job_applications", ["candidate_user_id"])
    op.create_unique_constraint(
        "uq_job_applications_job_candidate", "job_applications", ["job_id", "candidate_user_id"]
    )
    _enable_rls("job_applications")


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON "job_applications"')
    op.drop_table("job_applications")
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON "job_openings"')
    op.drop_table("job_openings")