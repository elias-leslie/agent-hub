"""retire the last two EOL NVIDIA NIM models

Revision ID: e6a2c40b91d5
Revises: d4f1a8c62e97
Create Date: 2026-08-17 19:20:00.000000

Follow-up to a7b8c9d0e1f2. Those two ids were still active because their end of
life only surfaced when they were probed directly:

- ``nvidia/deepseek-v4-flash``  HTTP 410, EOL 2026-08-07 — superseded upstream by
  ``deepseek-ai/deepseek-v4-flash-0731``
- ``nvidia/minimax-m2.7``       HTTP 410, EOL 2026-07-27 — superseded upstream by
  ``minimaxai/minimax-m3``

Both replacements are seeded and probed live, so nothing loses coverage.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6a2c40b91d5"
down_revision: str | Sequence[str] | None = "d4f1a8c62e97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEACTIVATED: list[tuple[str, str]] = [
    ("nvidia/deepseek-v4-flash", "retired_2026-08-17; nim_eol_2026-08-07_http_410"),
    ("nvidia/minimax-m2.7", "retired_2026-08-17; nim_eol_2026-07-27_http_410"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for model_id, availability in DEACTIVATED:
        conn.execute(
            sa.text(
                "UPDATE models SET is_active = false, availability = :availability, "
                "updated_at = now() WHERE id = :id"
            ),
            {"id": model_id, "availability": availability},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for model_id, _ in DEACTIVATED:
        conn.execute(
            sa.text("UPDATE models SET is_active = true, updated_at = now() WHERE id = :id"),
            {"id": model_id},
        )
