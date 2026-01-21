"""migrate_to_timestamptz

Revision ID: cd269ebb1e0d
Revises: e5f6g7h8i9j0
Create Date: 2026-01-20 21:55:44.381734

Migrate all 32 TIMESTAMP columns to TIMESTAMPTZ.
Existing data interpreted as America/New_York time (func.now() returns server local time).

WARNING: This migration uses ALTER COLUMN ... TYPE which drops DEFAULT constraints.
The fix migration f0a1b2c3d4e5_restore_timestamp_defaults.py restores them.
For future type changes, always re-apply defaults after ALTER COLUMN ... TYPE:

    ALTER TABLE t ALTER COLUMN c TYPE TIMESTAMPTZ USING c AT TIME ZONE 'tz';
    ALTER TABLE t ALTER COLUMN c SET DEFAULT now();  -- Must re-add!
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'cd269ebb1e0d'
down_revision: Union[str, Sequence[str], None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All columns that need migration: (table, column)
TIMESTAMP_COLUMNS = [
    ("agent_versions", "created_at"),
    ("agents", "created_at"),
    ("agents", "updated_at"),
    ("api_keys", "created_at"),
    ("api_keys", "expires_at"),
    ("api_keys", "last_used_at"),
    ("client_controls", "created_at"),
    ("client_controls", "disabled_at"),
    ("client_controls", "updated_at"),
    ("client_purpose_controls", "created_at"),
    ("client_purpose_controls", "disabled_at"),
    ("client_purpose_controls", "updated_at"),
    ("cost_logs", "created_at"),
    ("credentials", "created_at"),
    ("credentials", "updated_at"),
    ("message_feedback", "created_at"),
    ("messages", "created_at"),
    ("purpose_controls", "created_at"),
    ("purpose_controls", "disabled_at"),
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
    ("webhook_subscriptions", "last_triggered_at"),
    ("webhook_subscriptions", "updated_at"),
]


def upgrade() -> None:
    """Convert all TIMESTAMP columns to TIMESTAMPTZ.

    Existing data is interpreted as America/New_York time since the server
    was running in that timezone when func.now() recorded the values.
    """
    for table, column in TIMESTAMP_COLUMNS:
        op.execute(
            f"""
            ALTER TABLE {table}
            ALTER COLUMN {column}
            TYPE TIMESTAMPTZ
            USING {column} AT TIME ZONE 'America/New_York'
            """
        )


def downgrade() -> None:
    """Revert TIMESTAMPTZ columns back to TIMESTAMP.

    Converts back to America/New_York local time for compatibility.
    """
    for table, column in TIMESTAMP_COLUMNS:
        op.execute(
            f"""
            ALTER TABLE {table}
            ALTER COLUMN {column}
            TYPE TIMESTAMP
            USING {column} AT TIME ZONE 'America/New_York'
            """
        )
