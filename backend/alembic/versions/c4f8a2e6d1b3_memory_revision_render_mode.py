"""Record render_mode in memory revisions.

Revision ID: c4f8a2e6d1b3
Revises: b7e3c1d9a4f2

A global mandate memory switched to compact or summary rendering stops
reaching agents in full. Revisions now keep render_mode so that change shows
up in the owner note like any other. The latest revision of each memory gets
the memory's current value; older revisions stay unknown (NULL).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c4f8a2e6d1b3"
down_revision = "b7e3c1d9a4f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memory_revisions", sa.Column("render_mode", sa.String(length=16), nullable=True))
    op.execute(sa.text(
        """
        UPDATE memory_revisions r SET render_mode = m.render_mode
        FROM memories m,
             (SELECT DISTINCT ON (memory_id) id FROM memory_revisions
              WHERE memory_id IS NOT NULL
              ORDER BY memory_id, version DESC, created_at DESC) latest
        WHERE r.id = latest.id AND r.memory_id = m.id AND m.render_mode IS NOT NULL
        """
    ))


def downgrade() -> None:
    op.drop_column("memory_revisions", "render_mode")
