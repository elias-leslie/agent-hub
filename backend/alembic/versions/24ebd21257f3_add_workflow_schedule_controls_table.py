"""add_workflow_schedule_controls_table

Revision ID: 24ebd21257f3
Revises: ac9b84e23b92
Create Date: 2026-04-11 14:16:40.477700

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '24ebd21257f3'
down_revision: str | Sequence[str] | None = 'ac9b84e23b92'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "workflow_schedule_controls",
        sa.Column("schedule_id", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("schedule_id", name=op.f("pk_workflow_schedule_controls")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("workflow_schedule_controls")
