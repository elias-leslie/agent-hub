"""Lock the Safety Directive against deletion.

Revision ID: b7e3c1d9a4f2
Revises: a2d6b8e1f930

Every agent receives the global safety-directive prompt; deleting it through
the API would silently drop the safety rules. Edits stay allowed (and are noted
to the owner); only deletion is refused.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b7e3c1d9a4f2"
down_revision = "a2d6b8e1f930"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE prompts SET deletion_locked = true WHERE slug = 'safety-directive'"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE prompts SET deletion_locked = false WHERE slug = 'safety-directive'"))
