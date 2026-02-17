"""drop_retries_from_memory_injection_metrics

Revision ID: bd7f1acb476d
Revises: a1ff58549daa
Create Date: 2026-02-17 17:35:46.690270

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'bd7f1acb476d'
down_revision: Union[str, Sequence[str], None] = 'a1ff58549daa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the retries column from memory_injection_metrics.

    The column was never written at runtime — all callers of update_citation_metrics()
    omit the retries parameter (defaults to None), so the conditional write path
    was never triggered.
    """
    op.drop_column("memory_injection_metrics", "retries")


def downgrade() -> None:
    """Restore the retries column."""
    op.add_column(
        "memory_injection_metrics",
        sa.Column("retries", sa.Integer(), nullable=True),
    )
