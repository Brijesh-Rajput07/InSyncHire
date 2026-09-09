# LOCATION: services/migration_service/alembic_tenant/versions/20260101_0001_initial.py

"""initial tenant schema: organizations + tenant_user_memberships, RLS enabled

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01

This is the FIRST revision applied to every new tenant_<id>_db. It only
creates the two tables needed for tenant onboarding to complete
(Section: Tenant Onboarding Flow, step 4 -- "First user of the company
is auto-assigned company_admin role"). Every later milestone (Job
Service = M5, Interview Service = M8, etc.) adds its own tables to this
SAME versions/ chain as new revisions -- do not create a second chain.

RLS (Section 10b): every table gets
  ALTER TABLE ... ENABLE ROW LEVEL SECURITY
  CREATE POLICY ... USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
so a missed WHERE clause in application code still cannot leak another
tenant's rows -- this is the engine-level enforcement layer, with the
repository layer's explicit tenant_id filtering as the second,
independent layer on top.

Note: user_id / invited_by columns reference insynchire_global.global_users,
which lives in a DIFFERENT physical database -- Postgres cannot enforce
a cross-database FOREIGN KEY, so these are plain UUID columns, validated
at the application layer instead.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
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
        "organizations",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_organizations_tenant_id", "organizations", ["tenant_id"])
    _enable_rls("organizations")

    op.create_table(
        "tenant_user_memberships",
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            comment="company_admin | recruiter | interviewer | observer",
        ),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_tenant_user_memberships_tenant_id", "tenant_user_memberships", ["tenant_id"])
    op.create_index("ix_tenant_user_memberships_user_id", "tenant_user_memberships", ["user_id"])
    _enable_rls("tenant_user_memberships")


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON "tenant_user_memberships"')
    op.drop_table("tenant_user_memberships")
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON "organizations"')
    op.drop_table("organizations")
