"""seed the a-term service client

Revision ID: d2f7a9c3e6b4
Revises: c5e8a2d4f1b7
Create Date: 2026-10-17 11:00:00.000000

A-Term's prompt cleaner calls /api/complete for project a-term, which Agent Hub refuses without a registered
client. A-Term gets its own service client restricted to that project (its project permission row already
exists). The client id is generated here, not committed: the deployment copies it into A-Term's
AGENT_HUB_CLIENT_ID in its .env.local. Insert-only; an existing a-term client is left as it is.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2f7a9c3e6b4"
down_revision: str | Sequence[str] | None = "c5e8a2d4f1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECT_ID = "a-term"
_CLIENT_NAME = "a-term"


def upgrade() -> None:
    conn = op.get_bind()
    if conn.execute(
        sa.text("SELECT 1 FROM clients WHERE display_name = :n AND client_type = 'service'"), {"n": _CLIENT_NAME}
    ).scalar():
        return
    conn.execute(
        sa.text(
            """
            INSERT INTO clients (id, display_name, client_type, status, allowed_projects)
            VALUES (:id, :n, 'service', 'active', :allowed)
            """
        ),
        {"id": str(uuid.uuid4()), "n": _CLIENT_NAME, "allowed": json.dumps([_PROJECT_ID])},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM clients WHERE display_name = :n AND client_type = 'service'"), {"n": _CLIENT_NAME}
    )
