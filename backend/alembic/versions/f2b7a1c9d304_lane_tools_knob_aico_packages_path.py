"""Point the lane-tools.json context knob at its new place in the aico checkout.

Revision ID: f2b7a1c9d304
Revises: e6a1c4d9b207

Aico moved its code into packages/ (aico 252eaa40), so the file now lives at
packages/tether/src/lifecycle/tui/lane-tools.json. Downgrade restores the old path.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2b7a1c9d304"
down_revision: str | Sequence[str] | None = "e6a1c4d9b207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "tether/src/lifecycle/tui/lane-tools.json"
NEW = "packages/tether/src/lifecycle/tui/lane-tools.json"
UPDATE = "UPDATE context_knobs SET file_path = :to WHERE name = 'lane-tools.json' AND file_path = :frm"


def upgrade() -> None:
    op.execute(sa.text(UPDATE).bindparams(to=NEW, frm=OLD))


def downgrade() -> None:
    op.execute(sa.text(UPDATE).bindparams(to=OLD, frm=NEW))
