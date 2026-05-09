"""add_runtime_context_overrides

Revision ID: h4i5j6k7l8m9
Revises: g3h4i5j6k7l8
Create Date: 2026-05-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "h4i5j6k7l8m9"
down_revision: str | Sequence[str] | None = "g3h4i5j6k7l8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AGENTIC_CLI_PROMPT = """Direct concise. Use Agent Hub prompts and memory as source of truth. Use `st` for covered project workflows and `st check` for quality gates. Preserve user changes; no destructive commands without explicit approval. Use current repo evidence for live facts and memory for durable rules only. Keep startup context lean; move niche rules to scoped memories."""


def upgrade() -> None:
    op.create_table(
        "runtime_context_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("consumer_profile", sa.String(length=100), nullable=False),
        sa.Column("project_id", sa.String(length=100), nullable=True),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=20), server_default="include", nullable=False),
        sa.Column("position", sa.Integer(), server_default="50", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source_type IN ('prompt', 'memory')", name="ck_runtime_context_source_type"),
        sa.CheckConstraint("mode IN ('include', 'exclude', 'order')", name="ck_runtime_context_mode"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runtime_context_overrides_consumer_profile", "runtime_context_overrides", ["consumer_profile"])
    op.create_index("ix_runtime_context_overrides_project_id", "runtime_context_overrides", ["project_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_runtime_context_override_key
        ON runtime_context_overrides (
            consumer_profile,
            (COALESCE(project_id, '')),
            source_type,
            source_id
        )
        """
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO prompts (slug, name, content, description, is_global, enabled, prompt_type, deletion_locked)
            VALUES (
                'agentic-cli-startup-core',
                'Agentic CLI Startup Core',
                :content,
                'Shared compact startup rules for Codex, Claude, and other agentic CLI/TUI runtimes.',
                true,
                true,
                'runtime_context',
                false
            )
            ON CONFLICT (slug) DO UPDATE SET
                content = EXCLUDED.content,
                description = EXCLUDED.description,
                is_global = EXCLUDED.is_global,
                enabled = EXCLUDED.enabled,
                prompt_type = EXCLUDED.prompt_type,
                updated_at = now()
            """
        ),
        {"content": AGENTIC_CLI_PROMPT},
    )
    for profile in ("codex_startup", "claude_session_start", "gemini_startup"):
        conn.execute(
            sa.text(
                """
                INSERT INTO runtime_context_overrides
                    (consumer_profile, project_id, source_type, source_id, mode, position, enabled, note)
                VALUES
                    (:profile, NULL, 'prompt', 'agentic-cli-startup-core', 'include', 10, true, 'Default compact startup prompt')
                ON CONFLICT (consumer_profile, (COALESCE(project_id, '')), source_type, source_id)
                DO UPDATE SET mode = EXCLUDED.mode, position = EXCLUDED.position, enabled = EXCLUDED.enabled
                """
            ),
            {"profile": profile},
        )


def downgrade() -> None:
    op.drop_index("uq_runtime_context_override_key", table_name="runtime_context_overrides")
    op.drop_index("ix_runtime_context_overrides_project_id", table_name="runtime_context_overrides")
    op.drop_index("ix_runtime_context_overrides_consumer_profile", table_name="runtime_context_overrides")
    op.drop_table("runtime_context_overrides")
    op.execute("DELETE FROM prompts WHERE slug = 'agentic-cli-startup-core' AND prompt_type = 'runtime_context'")
