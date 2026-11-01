"""Memory revisions keep the row bookkeeping a recreated memory needs.

Revision ID: c4f7a2e9d815
Revises: b5e1c8a2d703

memory_revisions gains nullable copies of sensitivity_tier, review_status, the usage counters, lifecycle_score
and the memory's own created_at. Restoring a hard-deleted memory recreates it with these values from its latest
revision instead of defaults (a confidential memory no longer comes back as normal). NULL means the revision was
written before capture. Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4f7a2e9d815"
down_revision: str | Sequence[str] | None = "b5e1c8a2d703"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    ("sensitivity_tier", sa.String(20)),
    ("review_status", sa.String(20)),
    ("loaded_count", sa.Integer()),
    ("referenced_count", sa.Integer()),
    ("helpful_count", sa.Integer()),
    ("harmful_count", sa.Integer()),
    ("lifecycle_score", sa.Float()),
    ("memory_created_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    for name, column_type in COLUMNS:
        op.add_column("memory_revisions", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("memory_revisions", name)
