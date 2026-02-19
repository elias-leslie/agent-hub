"""migrate_model_ids_to_sonnet_46_opus_46

Revision ID: z3a4b5c6d7e8
Revises: y2z3a4b5c6d7
Create Date: 2026-02-19 12:00:00.000000

Migrates all model references from old versions to current:
- claude-sonnet-4-5 → claude-sonnet-4-6
- claude-opus-4-5 → claude-opus-4-6
- Removes dated suffixes (-20250514)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "z3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "3f75352000d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (old_value, new_value) pairs
MODEL_MIGRATIONS = [
    ("claude-sonnet-4-5", "claude-sonnet-4-6"),
    ("claude-sonnet-4-5-20250514", "claude-sonnet-4-6"),
    ("claude-opus-4-5", "claude-opus-4-6"),
    ("claude-opus-4-5-20250514", "claude-opus-4-6"),
    ("claude-haiku-4-5-20250514", "claude-haiku-4-5"),
]

# Tables and their model columns to migrate
TABLE_COLUMNS = [
    ("agents", "primary_model_id"),
    ("agents", "escalation_model_id"),
    ("sessions", "model"),
    ("session_events", "model_used"),
    ("cost_logs", "model"),
    ("request_logs", "model"),
    ("truncation_events", "model"),
    ("feedback_items", "model_used"),
    ("feedback_votes", "model_used"),
]


def _table_exists(conn: sa.Connection, table: str) -> bool:
    result = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"),
        {"t": table},
    )
    return result.scalar()


def upgrade() -> None:
    conn = op.get_bind()
    for old_val, new_val in MODEL_MIGRATIONS:
        for table, column in TABLE_COLUMNS:
            if not _table_exists(conn, table):
                continue
            op.execute(
                f"UPDATE {table} SET {column} = '{new_val}' "
                f"WHERE {column} = '{old_val}'"
            )
    # Also update fallback_models JSON array in agents table
    for old_val, new_val in MODEL_MIGRATIONS:
        op.execute(
            f"UPDATE agents SET fallback_models = "
            f"REPLACE(fallback_models::text, '\"{old_val}\"', '\"{new_val}\"')::jsonb "
            f"WHERE fallback_models::text LIKE '%{old_val}%'"
        )


def downgrade() -> None:
    conn = op.get_bind()
    reverse = [
        ("claude-sonnet-4-6", "claude-sonnet-4-5"),
        ("claude-opus-4-6", "claude-opus-4-5"),
    ]
    for new_val, old_val in reverse:
        for table, column in TABLE_COLUMNS:
            if not _table_exists(conn, table):
                continue
            op.execute(
                f"UPDATE {table} SET {column} = '{old_val}' "
                f"WHERE {column} = '{new_val}'"
            )
    for new_val, old_val in reverse:
        op.execute(
            f"UPDATE agents SET fallback_models = "
            f"REPLACE(fallback_models::text, '\"{new_val}\"', '\"{old_val}\"')::jsonb "
            f"WHERE fallback_models::text LIKE '%{new_val}%'"
        )
