"""Canonical context applicability and immutable operator evidence.

Revision ID: c7e92a160a31
Revises: be3b1a9a2e21
"""
import json

import sqlalchemy as sa

from alembic import op

revision = "c7e92a160a31"
down_revision = "be3b1a9a2e21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("models", sa.Column("supports_chat", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("models", sa.Column("supports_typed_judgment", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("models", sa.Column("max_state_question_tokens", sa.Integer(), nullable=True))
    for table in ("prompts", "prompt_revisions"):
        op.add_column(table, sa.Column("context_policy", sa.JSON(), nullable=True))
    op.create_table(
        "context_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_context_records_kind", "context_records", ["kind"])
    op.create_table(
        "context_judgments",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    connection = op.get_bind()
    prompts = connection.execute(sa.text("SELECT id, slug, is_global, owner_agent_id FROM prompts")).mappings()
    for row in prompts:
        projects = list(connection.execute(sa.text("""
            SELECT DISTINCT project_id FROM runtime_context_overrides
            WHERE source_type='prompt' AND source_id=:slug AND mode='include'
              AND enabled AND project_id IS NOT NULL
        """), {"slug": row["slug"]}).scalars())
        security = row["slug"] == "security-research-operating-policy"
        scope = "project" if security or (projects and not row["is_global"] and row["owner_agent_id"] is None) else "global" if row["is_global"] else "unassigned"
        policy = {"scope": scope, "targets": ["security-research"] if security else projects if scope == "project" else [],
                  "workflows": ["security-research"] if security else [], "activation": "always",
                  "task_types": [], "phases": [], "applicability": {}, "required": True, "format": "full"}
        connection.execute(sa.text("UPDATE prompts SET context_policy=CAST(:policy AS json), is_global=:global_scope WHERE id=:id"),
                           {"policy": json.dumps(policy), "global_scope": scope == "global", "id": row["id"]})
    # Preserve legacy overrides as placement controls. Selection now consults policy first.


def downgrade() -> None:
    for column in ("supports_chat", "supports_typed_judgment", "max_state_question_tokens"):
        op.drop_column("models", column)
    # Leave Security Research non-global on rollback; broadening it is not a safe schema rollback.
    op.drop_table("context_judgments")
    op.drop_index("ix_context_records_kind", table_name="context_records")
    op.drop_table("context_records")
    for table in ("prompt_revisions", "prompts"):
        op.drop_column(table, "context_policy")
