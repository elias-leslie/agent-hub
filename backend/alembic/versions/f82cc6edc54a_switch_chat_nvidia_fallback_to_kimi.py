"""switch nvidia qwen fallback models to kimi

Revision ID: f82cc6edc54a
Revises: 6561eb83acff
Create Date: 2026-03-06 18:02:00.516456

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f82cc6edc54a"
down_revision: str | Sequence[str] | None = "6561eb83acff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_MODEL = "nvidia/qwen3.5-397b-a17b"
NEW_MODEL = "nvidia/kimi-k2.5"


def _table_exists(conn: sa.Connection, table: str) -> bool:
    result = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"),
        {"t": table},
    )
    return bool(result.scalar())


def upgrade() -> None:
    """Replace NVIDIA Qwen fallback entries with the working Kimi model."""
    conn = op.get_bind()
    if not _table_exists(conn, "agents"):
        return
    conn.execute(
        sa.text(
            "UPDATE agents SET fallback_models = "
            "REPLACE(fallback_models::text, :old_json, :new_json)::jsonb "
            "WHERE fallback_models::text LIKE :pattern"
        ),
        {
            "old_json": f'"{OLD_MODEL}"',
            "new_json": f'"{NEW_MODEL}"',
            "pattern": f"%{OLD_MODEL}%",
        },
    )


def downgrade() -> None:
    """Restore the previous NVIDIA Qwen fallback entries."""
    conn = op.get_bind()
    if not _table_exists(conn, "agents"):
        return
    conn.execute(
        sa.text(
            "UPDATE agents SET fallback_models = "
            "REPLACE(fallback_models::text, :new_json, :old_json)::jsonb "
            "WHERE fallback_models::text LIKE :pattern"
        ),
        {
            "new_json": f'"{NEW_MODEL}"',
            "old_json": f'"{OLD_MODEL}"',
            "pattern": f"%{NEW_MODEL}%",
        },
    )
