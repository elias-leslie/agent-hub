"""Stop injecting "Recent Activity" into agent context by default.

The block lists other sessions' last replies in the project. It handed one model's mistakes ("pong", a false
"I'm Claude" line) to later agents and cost tokens on every call. Continuity is now opt-in per agent: the global
setting is switched off here. Agents are live data (edited through the API or ``st``, never a migration), so
the ones that carried the old default are switched off there. An agent that wants it sets ``continuity_enabled``
true in its own memory config.
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


def downgrade() -> None:
    op.alter_column("memory_settings", "continuity_enabled", server_default=sa.text("true"))
