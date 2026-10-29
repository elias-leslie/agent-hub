"""Stop injecting "Recent Activity" into agent context by default.

The block lists other sessions' last replies in the project. It handed one model's mistakes ("pong", a false
"I'm Claude" line) to later agents and cost tokens on every call. Continuity is now opt-in per agent: the global
setting and every agent that carried the old default (true) are switched off. An agent that wants it sets
``continuity_enabled`` true in its own memory config.
"""

import sqlalchemy as sa

from alembic import op

revision = "b8e3c5a7d9f2"
down_revision = "a7d2e9c4b1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("memory_settings", "continuity_enabled", server_default=sa.text("false"))
    op.execute("UPDATE memory_settings SET continuity_enabled = false")
    op.execute(
        "UPDATE agents SET memory_config = jsonb_set(memory_config::jsonb, '{continuity_enabled}', 'false'::jsonb)::json "
        "WHERE memory_config IS NOT NULL AND memory_config::jsonb ->> 'continuity_enabled' = 'true'"
    )


def downgrade() -> None:
    op.alter_column("memory_settings", "continuity_enabled", server_default=sa.text("true"))
