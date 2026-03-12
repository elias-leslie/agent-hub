"""consolidate agent prompt ownership

Revision ID: ca45411429f5
Revises: e25ac263bac8
Create Date: 2026-03-11 21:03:27.699455

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ca45411429f5'
down_revision: str | Sequence[str] | None = 'e25ac263bac8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERSONA_PERSONALITY_PROMPT = "persona-personality-document"
PERSONA_USER_CONTEXT_PROMPT = "persona-user-context"
PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT = "persona-heartbeat-instructions"


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    op.add_column(
        "prompts",
        sa.Column("owner_agent_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "prompts",
        sa.Column(
            "prompt_type",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'standard'"),
        ),
    )
    op.add_column(
        "prompts",
        sa.Column(
            "deletion_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_foreign_key(
        "fk_prompts_owner_agent_id_agents",
        "prompts",
        "agents",
        ["owner_agent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_prompts_owner_agent_id", "prompts", ["owner_agent_id"])
    op.create_index("ix_prompts_prompt_type", "prompts", ["prompt_type"])

    op.add_column(
        "prompt_revisions",
        sa.Column("owner_agent_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "prompt_revisions",
        sa.Column(
            "prompt_type",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'standard'"),
        ),
    )
    op.add_column(
        "prompt_revisions",
        sa.Column(
            "deletion_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    bind.execute(sa.text("UPDATE prompts SET prompt_type = 'standard', deletion_locked = false"))
    bind.execute(
        sa.text("UPDATE prompt_revisions SET prompt_type = 'standard', deletion_locked = false")
    )

    bind.execute(
        sa.text(
            """
            INSERT INTO prompts (
                slug,
                name,
                content,
                description,
                is_global,
                enabled,
                exclude_agents,
                owner_agent_id,
                prompt_type,
                deletion_locked
            )
            SELECT
                a.slug || '-system-prompt',
                a.name || ' System Prompt',
                a.system_prompt,
                'Primary system prompt for ' || a.name || '.',
                false,
                true,
                '[]'::json,
                a.id,
                'agent_system',
                true
            FROM agents a
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                content = EXCLUDED.content,
                description = EXCLUDED.description,
                owner_agent_id = EXCLUDED.owner_agent_id,
                prompt_type = EXCLUDED.prompt_type,
                deletion_locked = EXCLUDED.deletion_locked,
                enabled = EXCLUDED.enabled,
                exclude_agents = EXCLUDED.exclude_agents,
                updated_at = NOW()
            """
        )
    )

    bind.execute(
        sa.text(
            """
            INSERT INTO agent_prompts (agent_id, prompt_id, role, priority)
            SELECT
                a.id,
                p.id,
                'system',
                0
            FROM agents a
            JOIN prompts p
              ON p.slug = a.slug || '-system-prompt'
            ON CONFLICT (agent_id, prompt_id) DO UPDATE SET
                role = EXCLUDED.role,
                priority = EXCLUDED.priority
            """
        )
    )

    bind.execute(
        sa.text(
            f"""
            INSERT INTO prompts (
                slug,
                name,
                content,
                description,
                is_global,
                enabled,
                exclude_agents,
                owner_agent_id,
                prompt_type,
                deletion_locked
            )
            SELECT
                '{PERSONA_PERSONALITY_PROMPT}',
                'Personality Document',
                COALESCE(persona.personality, ''),
                'Jenny''s editable personality document.',
                false,
                true,
                '[]'::json,
                a.id,
                'persona_personality',
                false
            FROM persona
            JOIN agents a ON a.id = persona.agent_id
            WHERE a.slug = 'persona'
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                content = EXCLUDED.content,
                description = EXCLUDED.description,
                owner_agent_id = EXCLUDED.owner_agent_id,
                prompt_type = EXCLUDED.prompt_type,
                deletion_locked = EXCLUDED.deletion_locked,
                enabled = EXCLUDED.enabled,
                updated_at = NOW()
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            INSERT INTO prompts (
                slug,
                name,
                content,
                description,
                is_global,
                enabled,
                exclude_agents,
                owner_agent_id,
                prompt_type,
                deletion_locked
            )
            SELECT
                '{PERSONA_USER_CONTEXT_PROMPT}',
                'User Context',
                COALESCE(persona.user_context, ''),
                'Jenny''s editable freeform user notes.',
                false,
                true,
                '[]'::json,
                a.id,
                'persona_user_context',
                false
            FROM persona
            JOIN agents a ON a.id = persona.agent_id
            WHERE a.slug = 'persona'
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                content = EXCLUDED.content,
                description = EXCLUDED.description,
                owner_agent_id = EXCLUDED.owner_agent_id,
                prompt_type = EXCLUDED.prompt_type,
                deletion_locked = EXCLUDED.deletion_locked,
                enabled = EXCLUDED.enabled,
                updated_at = NOW()
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            UPDATE prompts
            SET
                owner_agent_id = a.id,
                prompt_type = 'persona_heartbeat_instructions',
                deletion_locked = false,
                updated_at = NOW()
            FROM agents a
            WHERE prompts.slug = '{PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT}'
              AND a.slug = 'persona'
            """
        )
    )

    bind.execute(
        sa.text(
            f"""
            INSERT INTO agent_prompts (agent_id, prompt_id, role, priority)
            SELECT
                a.id,
                p.id,
                link.role,
                link.priority
            FROM agents a
            JOIN (
                VALUES
                    ('persona-system-prompt', 'system', 0),
                    ('persona-safety', 'system', 10),
                    ('{PERSONA_PERSONALITY_PROMPT}', 'persona-personality', 20),
                    ('{PERSONA_USER_CONTEXT_PROMPT}', 'persona-user-context', 30),
                    ('{PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT}', 'heartbeat-instructions', 40)
            ) AS link(prompt_slug, role, priority) ON TRUE
            JOIN prompts p ON p.slug = link.prompt_slug
            WHERE a.slug = 'persona'
            ON CONFLICT (agent_id, prompt_id) DO UPDATE SET
                role = EXCLUDED.role,
                priority = EXCLUDED.priority
            """
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            DELETE FROM prompts
            WHERE prompt_type = 'agent_system'
               OR slug IN (
                    :personality_slug,
                    :user_context_slug
               )
            """
        ),
        {
            "personality_slug": PERSONA_PERSONALITY_PROMPT,
            "user_context_slug": PERSONA_USER_CONTEXT_PROMPT,
        },
    )

    op.drop_column("prompt_revisions", "deletion_locked")
    op.drop_column("prompt_revisions", "prompt_type")
    op.drop_column("prompt_revisions", "owner_agent_id")

    op.drop_index("ix_prompts_prompt_type", table_name="prompts")
    op.drop_index("ix_prompts_owner_agent_id", table_name="prompts")
    op.drop_constraint("fk_prompts_owner_agent_id_agents", "prompts", type_="foreignkey")
    op.drop_column("prompts", "deletion_locked")
    op.drop_column("prompts", "prompt_type")
    op.drop_column("prompts", "owner_agent_id")
