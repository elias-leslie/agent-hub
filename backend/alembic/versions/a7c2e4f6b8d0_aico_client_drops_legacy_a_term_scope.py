"""drop the legacy a-term project from the aico service client

Revision ID: a7c2e4f6b8d0
Revises: f1b3d5a7c9e2
Create Date: 2026-10-23

The aico client kept project `a-term` in allowed_projects only because the old Python web backend's prompt
cleaner sent that id. That backend is replaced by aico-web, which sends no project to Agent Hub (only
`X-Client-Id` on GET /api/models), so the client now allows `aico` alone. Downgrade adds `a-term` back.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c2e4f6b8d0"
down_revision: str | Sequence[str] | None = "f1b3d5a7c9e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_allowed(projects: list[str]) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE clients SET allowed_projects = :allowed, updated_at = NOW()"
            " WHERE display_name = 'aico' AND client_type = 'service'"
        ),
        {"allowed": json.dumps(projects)},
    )


def upgrade() -> None:
    _set_allowed(["aico"])


def downgrade() -> None:
    _set_allowed(["aico", "a-term"])
