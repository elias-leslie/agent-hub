"""Add an audio-capable quota fallback for the game audio critic.

Revision ID: 6e3c4c3cffac
Revises: f01de1c4adc1
Create Date: 2026-07-15 23:01:30.107185

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6e3c4c3cffac"
down_revision: str | Sequence[str] | None = "f01de1c4adc1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AGENT_SLUG = "game-audio-critic"
PRIMARY_MODEL_ID = "gemini-3.5-flash"
FALLBACK_MODEL_ID = "gemini-2.5-flash"


def upgrade() -> None:
    """Keep audio review available when the 3.5 project quota is exhausted."""

    op.execute(
        sa.text(
            """
            UPDATE agents
            SET fallback_models = CAST(:fallback_models AS json),
                version = version + 1,
                updated_at = now()
            WHERE slug = :agent_slug
              AND primary_model_id = :primary_model_id
              AND fallback_models::jsonb = CAST('[]' AS jsonb)
            """
        ).bindparams(
            agent_slug=AGENT_SLUG,
            primary_model_id=PRIMARY_MODEL_ID,
            fallback_models=f'["{FALLBACK_MODEL_ID}"]',
        )
    )


def downgrade() -> None:
    """Remove only the exact fallback installed by this migration."""

    op.execute(
        sa.text(
            """
            UPDATE agents
            SET fallback_models = CAST('[]' AS json),
                version = version + 1,
                updated_at = now()
            WHERE slug = :agent_slug
              AND primary_model_id = :primary_model_id
              AND fallback_models::jsonb = CAST(:fallback_models AS jsonb)
            """
        ).bindparams(
            agent_slug=AGENT_SLUG,
            primary_model_id=PRIMARY_MODEL_ID,
            fallback_models=f'["{FALLBACK_MODEL_ID}"]',
        )
    )
