"""move A-Term's service client, permission row and terminal memories to aico

Revision ID: f1b3d5a7c9e2
Revises: e3a7c9d1f502
Create Date: 2026-10-23

A-Term and Tether merged into the aico project. The seeded `a-term` service client becomes `aico` under the
same client id, so the web app's AGENT_HUB_CLIENT_ID keeps working; it still allows project `a-term` because the
web app's prompt cleaner sends that id until it is rewritten. A-Term's project_permissions row moves to aico
(unless aico already has one), and project memories scoped to the legacy ids `terminal`/`a-term` move to aico.
Downgrade restores the client and permission row; moved memories stay on aico.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1b3d5a7c9e2"
down_revision: str | Sequence[str] | None = "e3a7c9d1f502"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROOT = "/srv/workspaces/projects/{}"


def upgrade() -> None:
    conn = op.get_bind()
    if not conn.execute(
        sa.text("SELECT 1 FROM clients WHERE display_name = 'aico' AND client_type = 'service'")
    ).scalar():
        conn.execute(
            sa.text(
                "UPDATE clients SET display_name = 'aico', allowed_projects = :allowed, updated_at = NOW()"
                " WHERE display_name = 'a-term' AND client_type = 'service'"
            ),
            {"allowed": json.dumps(["aico", "a-term"])},
        )
    conn.execute(
        sa.text(
            "UPDATE project_permissions SET project_id = 'aico', root_path = :root, updated_at = NOW()"
            " WHERE project_id = 'a-term' AND NOT EXISTS (SELECT 1 FROM project_permissions WHERE project_id = 'aico')"
        ),
        {"root": _ROOT.format("aico")},
    )
    conn.execute(
        sa.text(
            "UPDATE memories SET scope_id = 'aico', updated_at = NOW()"
            " WHERE scope = 'project' AND scope_id IN ('terminal', 'a-term')"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE clients SET display_name = 'a-term', allowed_projects = :allowed, updated_at = NOW()"
            " WHERE display_name = 'aico' AND client_type = 'service'"
        ),
        {"allowed": json.dumps(["a-term"])},
    )
    conn.execute(
        sa.text(
            "UPDATE project_permissions SET project_id = 'a-term', root_path = :root, updated_at = NOW()"
            " WHERE project_id = 'aico' AND root_path = :aico_root"
        ),
        {"root": _ROOT.format("a-term"), "aico_root": _ROOT.format("aico")},
    )
