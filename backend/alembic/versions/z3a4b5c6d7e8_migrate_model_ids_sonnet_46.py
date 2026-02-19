"""migrate_model_ids_to_sonnet_46_opus_46

Revision ID: z3a4b5c6d7e8
Revises: 3f75352000d3
Create Date: 2026-02-19 12:00:00.000000

Migrates all model references from old versions to current:
- claude-sonnet-4-5 → claude-sonnet-4-6
- claude-opus-4-5 → claude-opus-4-6
- Removes dated suffixes (-20250514, -20250929)
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
    ("claude-sonnet-4-5-20250929", "claude-sonnet-4-6"),
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
            conn.execute(
                sa.text(f"UPDATE {table} SET {column} = :new_val WHERE {column} = :old_val"),
                {"new_val": new_val, "old_val": old_val},
            )
    # Also update fallback_models JSON array in agents table
    if _table_exists(conn, "agents"):
        for old_val, new_val in MODEL_MIGRATIONS:
            conn.execute(
                sa.text(
                    "UPDATE agents SET fallback_models = "
                    "REPLACE(fallback_models::text, :old_json, :new_json)::jsonb "
                    "WHERE fallback_models::text LIKE :pattern"
                ),
                {
                    "old_json": f'"{old_val}"',
                    "new_json": f'"{new_val}"',
                    "pattern": f"%{old_val}%",
                },
            )


# Downgrade is best-effort: this is a clean-break migration.
# Dated variants (-20250514, -20250929) and haiku are NOT reversed
# because no code path references the old dated IDs anymore.
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
            conn.execute(
                sa.text(f"UPDATE {table} SET {column} = :old_val WHERE {column} = :new_val"),
                {"old_val": old_val, "new_val": new_val},
            )
    if _table_exists(conn, "agents"):
        for new_val, old_val in reverse:
            conn.execute(
                sa.text(
                    "UPDATE agents SET fallback_models = "
                    "REPLACE(fallback_models::text, :new_json, :old_json)::jsonb "
                    "WHERE fallback_models::text LIKE :pattern"
                ),
                {
                    "new_json": f'"{new_val}"',
                    "old_json": f'"{old_val}"',
                    "pattern": f"%{new_val}%",
                },
            )
