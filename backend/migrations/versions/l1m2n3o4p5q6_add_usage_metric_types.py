"""add_usage_metric_types_helpful_harmful

Revision ID: l1m2n3o4p5q6
Revises: k0l1m2n3o4p5
Create Date: 2026-01-27 05:45:00.000000

Adds 'helpful' and 'harmful' values to usage_metric_type enum
for ACE-aligned agent rating feedback.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "l1m2n3o4p5q6"
down_revision: str | Sequence[str] | None = "k0l1m2n3o4p5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add 'helpful' and 'harmful' to usage_metric_type enum."""
    op.execute("ALTER TYPE usage_metric_type ADD VALUE IF NOT EXISTS 'helpful'")
    op.execute("ALTER TYPE usage_metric_type ADD VALUE IF NOT EXISTS 'harmful'")


def downgrade() -> None:
    """Cannot remove enum values in PostgreSQL - would need to recreate type."""
    pass
