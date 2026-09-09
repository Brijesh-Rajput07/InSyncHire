# LOCATION: services/migration_service/alembic_tenant/versions/20260201_0002_invited_users.py

"""add invited_users table (Task F / M3, Tenant Service)

Revision ID: 0002_invited_users
Revises: 0001_initial
Create Date: 2026-02-01

Added by Tenant Service (M3) to the SAME tenant migration chain
Migration Service owns (per that suite's env.py: every future
milestone adds a revision here, never a second chain).

company_admin invites a user by email; the invite lives here until
accepted, at which point Tenant Service creates the corresponding
tenant_user_memberships row (see 0001_initial.py).

RLS follows the same pattern as every other tenant table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_invited_users"
down_revision: Union[str, None] = "0001_initial"
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
        "invited_users",
        sa.Column("invite_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            comment="company_admin | recruiter | interviewer | observer",
        ),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_invited_users_tenant_id", "invited_users", ["tenant_id"])
    op.create_index("ix_invited_users_email", "invited_users", ["email"])
    op.create_index("ix_invited_users_token_hash", "invited_users", ["token_hash"], unique=True)
    _enable_rls("invited_users")


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON "invited_users"')
    op.drop_table("invited_users")
