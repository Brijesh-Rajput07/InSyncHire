# LOCATION: services/migration_service/alembic_tenant/versions/20260301_0003_agent_and_process_logs.py

"""add agent_decision_logs, agent_guardrail_logs, process_logs (FIX-M1)

Revision ID: 0003_agent_and_process_logs
Revises: 0002_invited_users
Create Date: 2026-03-01

These 3 tables were missing from the tenant migration suite (Section 4,
FIX-M1): every tenant provisioned before this revision existed is
missing them. After adding this revision:
  1. New tenants get these tables automatically (they're now part of
     `upgrade head`, which Migration Service always runs on provisioning).
  2. EXISTING tenants need this revision applied via the system-admin
     `migrate-all-tenants` CLI command (see migration_service/main.py) --
     never applied inline in any API request path.

Columns match Section 5 of the project plan exactly. `output` /
`guardrail_actions_taken` / `before_state` / `after_state` use JSONB
(Postgres-only -- these tables are never exercised against SQLite in
tests for that reason; the ORM-level equivalents, when a service
builds SQLAlchemy models against them, should use the same cross-dialect
JSON pattern as elsewhere in this repo if SQLite testability is needed).

RLS follows the same pattern as every other tenant table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_agent_and_process_logs"
down_revision: Union[str, None] = "0002_invited_users"
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
        "agent_decision_logs",
        sa.Column("log_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("trigger_type", sa.String(100), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("guardrail_actions_taken", postgresql.JSONB(), nullable=True),
        sa.Column("human_override", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("override_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("fallback_triggered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_decision_logs_tenant_id", "agent_decision_logs", ["tenant_id"])
    op.create_index("ix_agent_decision_logs_session_id", "agent_decision_logs", ["session_id"])
    _enable_rls("agent_decision_logs")

    op.create_table(
        "agent_guardrail_logs",
        sa.Column("log_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("guardrail_layer", sa.Integer(), nullable=False),
        sa.Column("guardrail_rule", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("trigger_reason", sa.Text(), nullable=True),
        sa.Column("raw_flagged_content", sa.Text(), nullable=True),
        # ^ encrypted at the repository layer before being written here
        # (Section 10g), same pattern as tenants.db_connection_string
        # in insynchire_global -- never plaintext at rest.
        sa.Column(
            "action_taken", sa.String(20), nullable=False,
            comment="BLOCKED | SANITIZED | FLAGGED | PASSED",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("guardrail_layer BETWEEN 1 AND 5", name="ck_agent_guardrail_logs_layer_range"),
    )
    op.create_index("ix_agent_guardrail_logs_tenant_id", "agent_guardrail_logs", ["tenant_id"])
    op.create_index("ix_agent_guardrail_logs_session_id", "agent_guardrail_logs", ["session_id"])
    _enable_rls("agent_guardrail_logs")

    op.create_table(
        "process_logs",
        sa.Column("log_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(100), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=True),
        sa.Column("outcome", sa.String(50), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_process_logs_tenant_id", "process_logs", ["tenant_id"])
    op.create_index("ix_process_logs_entity", "process_logs", ["entity_type", "entity_id"])
    _enable_rls("process_logs")


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON "process_logs"')
    op.drop_table("process_logs")
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON "agent_guardrail_logs"')
    op.drop_table("agent_guardrail_logs")
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON "agent_decision_logs"')
    op.drop_table("agent_decision_logs")
