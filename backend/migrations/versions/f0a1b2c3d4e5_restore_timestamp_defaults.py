"""restore_timestamp_defaults

Revision ID: f0a1b2c3d4e5
Revises: cd269ebb1e0d
Create Date: 2026-01-20 23:55:00.000000

Fix: Restore DEFAULT now() to timestamp columns dropped by TIMESTAMPTZ migration.

The cd269ebb1e0d migration used ALTER COLUMN ... TYPE TIMESTAMPTZ which implicitly
drops DEFAULT constraints in PostgreSQL. This migration restores them.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'cd269ebb1e0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All columns that need DEFAULT now() restored: (table, column)
# These match the models with server_default=func.now()
COLUMNS_WITH_DEFAULTS = [
    ("agent_versions", "created_at"),
    ("agents", "created_at"),
    ("agents", "updated_at"),
    ("api_keys", "created_at"),
    ("client_controls", "created_at"),
    ("client_controls", "updated_at"),
    ("client_purpose_controls", "created_at"),
    ("client_purpose_controls", "updated_at"),
    ("cost_logs", "created_at"),
    ("credentials", "created_at"),
    ("credentials", "updated_at"),
    ("message_feedback", "created_at"),
    ("messages", "created_at"),
    ("purpose_controls", "created_at"),
    ("purpose_controls", "updated_at"),
    ("roundtable_messages", "created_at"),
    ("roundtable_sessions", "created_at"),
    ("roundtable_sessions", "updated_at"),
    ("sessions", "created_at"),
    ("sessions", "updated_at"),
    ("truncation_events", "created_at"),
    ("usage_stats", "timestamp"),
    ("user_preferences", "created_at"),
    ("user_preferences", "updated_at"),
    ("webhook_subscriptions", "created_at"),
    ("webhook_subscriptions", "updated_at"),
]


def upgrade() -> None:
    """Restore DEFAULT now() to all timestamp columns that should have it."""
    for table, column in COLUMNS_WITH_DEFAULTS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT now()"
        )


def downgrade() -> None:
    """Remove defaults (revert to state after TIMESTAMPTZ migration)."""
    for table, column in COLUMNS_WITH_DEFAULTS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT"
        )
