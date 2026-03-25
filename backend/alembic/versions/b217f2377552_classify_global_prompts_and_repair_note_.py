"""classify global prompts and repair note titler prompt

Revision ID: b217f2377552
Revises: 46da0d007484
Create Date: 2026-03-24 22:09:53.184492

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b217f2377552'
down_revision: str | Sequence[str] | None = '46da0d007484'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STANDARD_PROMPT_TYPE = "standard"
AGENT_SYSTEM_PROMPT_TYPE = "agent_system"
GLOBAL_MANDATE_PROMPT_TYPE = "global_mandate"
GLOBAL_GUARDRAIL_PROMPT_TYPE = "global_guardrail"

NOTE_TITLER_AGENT_SLUG = "note-titler"
LEGACY_NOTE_TITLER_PROMPT_SLUG = "note-titler-system"
CANONICAL_NOTE_TITLER_PROMPT_SLUG = "note-titler-system-prompt"


def upgrade() -> None:
    """Upgrade data."""
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            UPDATE prompts
               SET prompt_type = CASE
                   WHEN slug IN ('narration-tags', 'web-research-routine') THEN :mandate_type
                   WHEN slug = 'safety-directive' THEN :guardrail_type
                   ELSE prompt_type
               END
             WHERE slug IN ('narration-tags', 'web-research-routine', 'safety-directive')
            """
        ),
        {
            "mandate_type": GLOBAL_MANDATE_PROMPT_TYPE,
            "guardrail_type": GLOBAL_GUARDRAIL_PROMPT_TYPE,
        },
    )

    agent_id = bind.execute(
        sa.text("SELECT id FROM agents WHERE slug = :slug"),
        {"slug": NOTE_TITLER_AGENT_SLUG},
    ).scalar()
    if agent_id is None:
        return

    prompt_id = bind.execute(
        sa.text("SELECT id FROM prompts WHERE slug = :slug"),
        {"slug": CANONICAL_NOTE_TITLER_PROMPT_SLUG},
    ).scalar()
    legacy_prompt_id = bind.execute(
        sa.text("SELECT id FROM prompts WHERE slug = :slug"),
        {"slug": LEGACY_NOTE_TITLER_PROMPT_SLUG},
    ).scalar()

    if prompt_id is None and legacy_prompt_id is not None:
        bind.execute(
            sa.text(
                """
                UPDATE prompts
                   SET slug = :canonical_slug,
                       name = 'Note Titler System Prompt',
                       content = (
                           SELECT system_prompt
                             FROM agents
                            WHERE id = :agent_id
                       ),
                       is_global = false,
                       enabled = true,
                       exclude_agents = '[]'::json,
                       owner_agent_id = :agent_id,
                       prompt_type = :prompt_type,
                       deletion_locked = true,
                       updated_at = NOW()
                 WHERE id = :prompt_id
                """
            ),
            {
                "canonical_slug": CANONICAL_NOTE_TITLER_PROMPT_SLUG,
                "agent_id": agent_id,
                "prompt_type": AGENT_SYSTEM_PROMPT_TYPE,
                "prompt_id": legacy_prompt_id,
            },
        )
        prompt_id = legacy_prompt_id
    elif prompt_id is not None:
        bind.execute(
            sa.text(
                """
                UPDATE prompts
                   SET name = 'Note Titler System Prompt',
                       content = (
                           SELECT system_prompt
                             FROM agents
                            WHERE id = :agent_id
                       ),
                       is_global = false,
                       enabled = true,
                       exclude_agents = '[]'::json,
                       owner_agent_id = :agent_id,
                       prompt_type = :prompt_type,
                       deletion_locked = true,
                       updated_at = NOW()
                 WHERE id = :prompt_id
                """
            ),
            {
                "agent_id": agent_id,
                "prompt_type": AGENT_SYSTEM_PROMPT_TYPE,
                "prompt_id": prompt_id,
            },
        )
        if legacy_prompt_id is not None and legacy_prompt_id != prompt_id:
            bind.execute(
                sa.text("DELETE FROM prompts WHERE id = :prompt_id"),
                {"prompt_id": legacy_prompt_id},
            )
    else:
        system_prompt = bind.execute(
            sa.text("SELECT system_prompt FROM agents WHERE id = :agent_id"),
            {"agent_id": agent_id},
        ).scalar()
        if system_prompt:
            prompt_id = bind.execute(
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
                    ) VALUES (
                        :slug,
                        'Note Titler System Prompt',
                        :content,
                        'Primary system prompt for Note Titler.',
                        false,
                        true,
                        '[]'::json,
                        :agent_id,
                        :prompt_type,
                        true
                    )
                    RETURNING id
                    """
                ),
                {
                    "slug": CANONICAL_NOTE_TITLER_PROMPT_SLUG,
                    "content": system_prompt.strip(),
                    "agent_id": agent_id,
                    "prompt_type": AGENT_SYSTEM_PROMPT_TYPE,
                },
            ).scalar()

    if prompt_id is not None:
        bind.execute(
            sa.text(
                """
                INSERT INTO agent_prompts (agent_id, prompt_id, role, priority)
                VALUES (:agent_id, :prompt_id, 'system', 0)
                ON CONFLICT (agent_id, prompt_id)
                DO UPDATE SET role = EXCLUDED.role, priority = EXCLUDED.priority
                """
            ),
            {"agent_id": agent_id, "prompt_id": prompt_id},
        )


def downgrade() -> None:
    """Downgrade data."""
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            UPDATE prompts
               SET prompt_type = :standard_type
             WHERE slug IN ('narration-tags', 'web-research-routine', 'safety-directive')
            """
        ),
        {"standard_type": STANDARD_PROMPT_TYPE},
    )

    agent_id = bind.execute(
        sa.text("SELECT id FROM agents WHERE slug = :slug"),
        {"slug": NOTE_TITLER_AGENT_SLUG},
    ).scalar()
    if agent_id is None:
        return

    prompt_id = bind.execute(
        sa.text("SELECT id FROM prompts WHERE slug = :slug"),
        {"slug": CANONICAL_NOTE_TITLER_PROMPT_SLUG},
    ).scalar()
    if prompt_id is None:
        return

    bind.execute(
        sa.text(
            """
            DELETE FROM agent_prompts
             WHERE agent_id = :agent_id
               AND prompt_id = :prompt_id
            """
        ),
        {"agent_id": agent_id, "prompt_id": prompt_id},
    )
    bind.execute(
        sa.text(
            """
            UPDATE prompts
               SET slug = :legacy_slug,
                   owner_agent_id = NULL,
                   prompt_type = :standard_type,
                   updated_at = NOW()
             WHERE id = :prompt_id
            """
        ),
        {
            "legacy_slug": LEGACY_NOTE_TITLER_PROMPT_SLUG,
            "standard_type": STANDARD_PROMPT_TYPE,
            "prompt_id": prompt_id,
        },
    )
