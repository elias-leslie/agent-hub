"""migrate_persona_heartbeat_prompt

Revision ID: c6d7e8f9a0b1
Revises: a4b5c6d7e8f9
Create Date: 2026-03-08 12:20:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c6d7e8f9a0b1"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


PROMPT_SLUG = "persona-heartbeat-instructions"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO prompts (slug, name, content, description, is_global, enabled, exclude_agents)
            SELECT
                :slug,
                'Persona Heartbeat Instructions',
                heartbeat_instructions,
                'Jenny-specific mutable guidance for heartbeat runs.',
                false,
                true,
                '[]'::json
            FROM persona
            WHERE heartbeat_instructions IS NOT NULL
              AND btrim(heartbeat_instructions) <> ''
              AND NOT EXISTS (
                    SELECT 1 FROM prompts p WHERE p.slug = :slug
              )
            """
        ),
        {"slug": PROMPT_SLUG},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE FROM prompts
            WHERE slug = :slug
              AND description = 'Jenny-specific mutable guidance for heartbeat runs.'
            """
        ),
        {"slug": PROMPT_SLUG},
    )
