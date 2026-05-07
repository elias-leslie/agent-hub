"""canonicalize_project_permission_tiers

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-05-07 22:20:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Migrate legacy write/yolo tiers to canonical full."""
    op.execute(
        """
        UPDATE project_permissions
        SET permission_tier = 'full'
        WHERE lower(permission_tier) IN ('write', 'yolo')
        """
    )


def downgrade() -> None:
    """Restore full as legacy yolo for older code."""
    op.execute(
        """
        UPDATE project_permissions
        SET permission_tier = 'yolo'
        WHERE lower(permission_tier) = 'full'
        """
    )
