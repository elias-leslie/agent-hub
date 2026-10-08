"""Remove the retired Neri local-worker routing prompt.

Revision ID: g2f3e4d5c6b7
Revises: f1e2d3c4b5a6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g2f3e4d5c6b7"
down_revision: str | Sequence[str] | None = "f1e2d3c4b5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROMPT_SLUG = "neri-local-worker-routing"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM agent_prompts WHERE prompt_id IN "
            "(SELECT id FROM prompts WHERE slug = :slug)"
        ),
        {"slug": _PROMPT_SLUG},
    )
    bind.execute(
        sa.text("DELETE FROM prompts WHERE slug = :slug"),
        {"slug": _PROMPT_SLUG},
    )


def downgrade() -> None:
    raise RuntimeError(
        "The retired Neri local-worker prompt is intentionally not recreated; "
        "restore the pre-cleanup Agent Hub snapshot if rollback is required."
    )
