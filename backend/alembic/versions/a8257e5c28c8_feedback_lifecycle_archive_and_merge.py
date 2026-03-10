"""feedback lifecycle archive and merge

Revision ID: a8257e5c28c8
Revises: 706345626a08
Create Date: 2026-03-10 13:12:43.073095

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8257e5c28c8"
down_revision: str | Sequence[str] | None = "706345626a08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("ck_feedback_items_status", "feedback_items", type_="check")
    op.create_check_constraint(
        "ck_feedback_items_status",
        "feedback_items",
        "status IN ('open', 'acknowledged', 'resolved', 'wont_fix', 'archived')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "UPDATE feedback_items SET status = 'resolved' WHERE status = 'archived'"
    )
    op.drop_constraint("ck_feedback_items_status", "feedback_items", type_="check")
    op.create_check_constraint(
        "ck_feedback_items_status",
        "feedback_items",
        "status IN ('open', 'acknowledged', 'resolved', 'wont_fix')",
    )
