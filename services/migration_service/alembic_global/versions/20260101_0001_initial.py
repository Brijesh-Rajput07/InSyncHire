# LOCATION: services/migration_service/alembic_global/versions/20260101_0001_initial.py

"""initial insynchire_global schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subdomain", sa.String(63), nullable=False, unique=True),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("company_domain", sa.String(255), nullable=False, unique=True),
        sa.Column("db_connection_string", sa.Text(), nullable=True),
        sa.Column("plan", sa.String(50), nullable=False, server_default="trial"),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_index("ix_tenants_subdomain", "tenants", ["subdomain"])
    op.create_index("ix_tenants_company_domain", "tenants", ["company_domain"])

    op.create_table(
        "tenant_migrations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alembic_version", sa.String(64), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("applied_by_service", sa.String(100), nullable=False, server_default="migration_service"),
    )
    op.create_index("ix_tenant_migrations_tenant_id", "tenant_migrations", ["tenant_id"])

    op.create_table(
        "global_users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("account_type", sa.String(20), nullable=False),
    )
    op.create_index("ix_global_users_email", "global_users", ["email"])

    op.create_table(
        "global_user_resumes",
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("global_users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_url", sa.Text(), nullable=False),
        sa.Column("parsed_data", postgresql.JSONB(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_global_user_resumes_user_id", "global_user_resumes", ["user_id"])


def downgrade() -> None:
    op.drop_table("global_user_resumes")
    op.drop_table("global_users")
    op.drop_table("tenant_migrations")
    op.drop_table("tenants")
