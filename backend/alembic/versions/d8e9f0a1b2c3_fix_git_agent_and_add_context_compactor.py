"""fix_git_agent_and_add_context_compactor

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-04-14 18:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: str | Sequence[str] | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMPACTOR_SLUG = "context-compactor"
_COMPACTOR_PROMPT = (
    "Summarize earlier conversation for context compaction.\n\n"
    "Keep:\n"
    "- key decisions\n"
    "- user preferences and constraints\n"
    "- important tool results\n"
    "- open action items\n\n"
    "Drop greetings, filler, and repeated detail.\n"
    "Output only the compact summary text."
)
_COMPACTOR_MEMORY_CONFIG = {
    "injection_enabled": False,
    "project_index_enabled": False,
    "tool_capabilities_enabled": False,
    "include_mandates": False,
    "include_guardrails": False,
    "include_references": False,
    "reference_index_enabled": False,
    "continuity_enabled": False,
    "continuity_max_sessions": 5,
    "audience_tags": [],
    "exclude_tags": [],
    "exclude_memory_uuids": [],
}


def upgrade() -> None:
    bind = op.get_bind()
    agents_table = sa.table(
        "agents",
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("system_prompt", sa.Text),
        sa.column("primary_model_id", sa.String),
        sa.column("fallback_models", sa.JSON),
        sa.column("strategies", sa.JSON),
        sa.column("temperature", sa.Float),
        sa.column("thinking_level", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("is_coding_agent", sa.Boolean),
        sa.column("memory_config", sa.JSON),
        sa.column("version", sa.Integer),
    )

    bind.execute(
        sa.text(
            """
            UPDATE agents
            SET primary_model_id = :new_model,
                version = COALESCE(version, 0) + 1
            WHERE slug = 'git-agent' AND primary_model_id = :old_model
            """
        ),
        {"new_model": "codex/gpt-5.4", "old_model": "codex/gpt-5.3-codex-spark"},
    )

    exists = bind.execute(
        sa.select(sa.literal(1)).select_from(agents_table).where(agents_table.c.slug == _COMPACTOR_SLUG)
    ).scalar()
    if not exists:
        op.bulk_insert(
            agents_table,
            [
                {
                    "slug": _COMPACTOR_SLUG,
                    "name": "Context Compactor",
                    "description": "Summarizes older conversation turns when live session context needs compaction",
                    "system_prompt": _COMPACTOR_PROMPT,
                    "primary_model_id": "claude-haiku-4-5",
                    "fallback_models": ["gemini-3.1-flash-lite-preview", "codex/gpt-5.4"],
                    "strategies": {},
                    "temperature": 0.2,
                    "thinking_level": "none",
                    "is_active": True,
                    "is_coding_agent": False,
                    "memory_config": _COMPACTOR_MEMORY_CONFIG,
                    "version": 1,
                },
            ],
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM agents WHERE slug = :slug"), {"slug": _COMPACTOR_SLUG})
    bind.execute(
        sa.text(
            """
            UPDATE agents
            SET primary_model_id = :old_model,
                version = GREATEST(COALESCE(version, 1) - 1, 1)
            WHERE slug = 'git-agent' AND primary_model_id = :new_model
            """
        ),
        {"new_model": "codex/gpt-5.4", "old_model": "codex/gpt-5.3-codex-spark"},
    )
