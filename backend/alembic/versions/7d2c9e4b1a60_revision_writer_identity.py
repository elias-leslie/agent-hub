"""Revision writer identity: who made each memory and prompt revision.

Revision ID: 7d2c9e4b1a60
Revises: 3fbbbec251db

memory_revisions and prompt_revisions gain nullable writer columns: the writer kind (owner, agent, client,
system), the agent's context delivery hash and its Aico session id. They are resolved through
context_deliveries when read. NULL means the row was written before writer capture. Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7d2c9e4b1a60"
down_revision: str | Sequence[str] | None = "3fbbbec251db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("memory_revisions", "prompt_revisions")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("writer_kind", sa.String(16), nullable=True))
        op.add_column(table, sa.Column("writer_delivery", sa.String(128), nullable=True))
        op.add_column(table, sa.Column("writer_session", sa.String(128), nullable=True))
        op.create_index(f"ix_{table}_writer_session", table, ["writer_session"])


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_writer_session", table_name=table)
        op.drop_column(table, "writer_session")
        op.drop_column(table, "writer_delivery")
        op.drop_column(table, "writer_kind")
