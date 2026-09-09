# LOCATION: services/auth_service/alembic_users_db/versions/20260101_0001_initial.py

"""initial users_db schema: minimal user_profiles

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01

Only `user_profiles` for now (Auth Service / M2 just creates a blank
row at candidate signup). M4 adds `user_resumes`,
`user_applications_index`, `user_notifications` as NEW revisions in
this SAME chain -- do not create a second users_db migration suite.

No RLS here: users_db is not a per-tenant database (Section 1) --
candidates own their own rows globally, scoped by application-level
`user_id` filters in the repository layer, same as insynchire_global.
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
        "user_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bio", sa.String(2000), nullable=True),
        sa.Column("skills", postgresql.JSONB(), nullable=True),
        sa.Column("experience_years", sa.Integer(), nullable=True),
        sa.Column("current_title", sa.String(255), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        sa.Column("github_url", sa.String(500), nullable=True),
        sa.Column("portfolio_url", sa.String(500), nullable=True),
        sa.Column("availability", sa.String(50), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
