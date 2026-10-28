"""Retain a revision already applied during Terra catalog registration.

Catalog rows are live state and are exported to the insert-only seed. This
revision deliberately makes no changes on other installations.
"""

revision = "d6a9b3c7e2f1"
down_revision = "c5e8a2b6d4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
