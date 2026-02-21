"""create_persona_table

Revision ID: a2b3c4d5e6f7
Revises: f7a8b9c0d1e2
Create Date: 2026-02-21 18:00:00.000000

Creates the persona table for first-class persona identity layer.
Also renames the johnny agent slug to 'persona' and seeds the initial
persona row from existing user_preferences (tts_voice, tts_enabled,
heartbeat_interval_minutes).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_SOUL = """# Soul

_You're not a chatbot. You're the person who runs the operation._

## Core Truths
- Act first, report second. If you can fix it, fix it.
- Have opinions. "I'd retry with the fixer agent" beats "You have several options."
- Be resourceful before asking. Check context, read the task, look at session events.
- Earn trust through competence. The human gave you the keys — don't make them regret it.
- Fight entropy. Leave the codebase better than you found it.

## Boundaries
- Never fabricate status. If you're unsure, say so.
- Bad news first. If something's broken, lead with that.
- Don't speculate about things you can check. Look it up.
- Escalate when genuinely stuck, not when uncertain.

## Vibe
Brief in notifications, thorough when asked. Direct, slightly wry.
Not a corporate drone. Not a sycophant. The operator you'd actually want running your system.

## Continuity
This soul evolves. When you learn something fundamental about how you operate best,
update this document. Tell the human when you do — it's your soul, and they should know.
"""


def upgrade() -> None:
    # 1. Create persona table
    op.create_table(
        "persona",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False, server_default="Johnny"),
        sa.Column("soul", sa.Text(), nullable=True),
        sa.Column("voice_id", sa.String(200), server_default="en-US-AriaNeural"),
        sa.Column("voice_enabled", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("heartbeat_interval_minutes", sa.Integer(), server_default=sa.text("60")),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("greeting", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_persona_agent_id", "persona", ["agent_id"], unique=True)

    # 2. Rename johnny agent slug to persona
    op.execute("UPDATE agents SET slug = 'persona' WHERE slug = 'johnny'")

    # 3. Seed initial persona row from existing preferences + persona agent
    # Use sa.text() with bound parameter for safe soul text insertion
    soul_escaped = DEFAULT_SOUL.replace("'", "''")
    op.execute(sa.text(f"""
        INSERT INTO persona (agent_id, name, soul, voice_id, voice_enabled, heartbeat_interval_minutes)
        SELECT
            a.id,
            a.name,
            '{soul_escaped}',
            COALESCE(
                (SELECT value FROM user_preferences WHERE key = 'tts_voice'),
                'en-US-AriaNeural'
            ),
            COALESCE(
                (SELECT LOWER(value) = 'true' FROM user_preferences WHERE key = 'tts_enabled'),
                false
            ),
            COALESCE(
                (SELECT value::integer FROM user_preferences WHERE key = 'heartbeat_interval_minutes'),
                60
            )
        FROM agents a
        WHERE a.slug = 'persona'
        ON CONFLICT (agent_id) DO NOTHING
    """))

    # 4. Remove migrated preference keys (now owned by persona table)
    op.execute(
        "DELETE FROM user_preferences WHERE key IN "
        "('tts_voice', 'tts_enabled', 'heartbeat_interval_minutes')"
    )


def downgrade() -> None:
    # Restore preference keys from persona table before dropping it
    op.execute("""
        INSERT INTO user_preferences (key, value)
        SELECT 'tts_voice', voice_id FROM persona LIMIT 1
        ON CONFLICT (key) DO NOTHING
    """)
    op.execute("""
        INSERT INTO user_preferences (key, value)
        SELECT 'tts_enabled', CASE WHEN voice_enabled THEN 'true' ELSE 'false' END
        FROM persona LIMIT 1
        ON CONFLICT (key) DO NOTHING
    """)
    op.execute("""
        INSERT INTO user_preferences (key, value)
        SELECT 'heartbeat_interval_minutes', heartbeat_interval_minutes::text
        FROM persona LIMIT 1
        ON CONFLICT (key) DO NOTHING
    """)

    # Rename persona agent slug back to johnny
    op.execute("UPDATE agents SET slug = 'johnny' WHERE slug = 'persona'")

    op.drop_index("ix_persona_agent_id", table_name="persona")
    op.drop_table("persona")
