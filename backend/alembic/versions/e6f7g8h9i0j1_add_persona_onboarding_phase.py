"""add_persona_onboarding_phase

Revision ID: e6f7g8h9i0j1
Revises: d5e6f7g8h9i0
Create Date: 2026-02-22 12:00:00.000000

Adds onboarding_phase to persona table, auto_tier to agents table,
backfills onboarding_phase from onboarding_complete, and updates
the persona agent identity from Johnny to Jenny.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6f7g8h9i0j1"
down_revision: str | Sequence[str] | None = "d5e6f7g8h9i0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add onboarding_phase to persona
    op.add_column(
        "persona",
        sa.Column(
            "onboarding_phase",
            sa.String(20),
            server_default="not_started",
            nullable=False,
        ),
    )

    # Backfill: already-onboarded personas get phase='complete'
    op.execute(
        sa.text(
            "UPDATE persona SET onboarding_phase = 'complete' "
            "WHERE onboarding_complete = true"
        )
    )

    # Add auto_tier to agents
    op.add_column(
        "agents",
        sa.Column(
            "auto_tier",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )

    # Enable auto_tier for persona agent
    op.execute(
        sa.text("UPDATE agents SET auto_tier = true WHERE slug = 'persona'")
    )

    # Update persona agent identity: Johnny -> Jenny
    op.execute(
        sa.text("UPDATE agents SET name = 'Jenny' WHERE slug = 'persona'")
    )

    # Update persona name: Johnny -> Jenny (only if still default)
    op.execute(
        sa.text("UPDATE persona SET name = 'Jenny' WHERE name = 'Johnny'")
    )


def downgrade() -> None:
    op.drop_column("persona", "onboarding_phase")
    op.drop_column("agents", "auto_tier")
    op.execute(
        sa.text("UPDATE agents SET name = 'Johnny' WHERE slug = 'persona'")
    )
    op.execute(
        sa.text("UPDATE persona SET name = 'Johnny' WHERE name = 'Jenny'")
    )
