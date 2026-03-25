"""canonicalize disabled memory config

Revision ID: 93da76ab0d27
Revises: e960dc14ef2f
Create Date: 2026-03-25 00:07:42.975073

"""
from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '93da76ab0d27'
down_revision: Union[str, Sequence[str], None] = 'e960dc14ef2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Clear subordinate memory flags when injection is disabled."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, memory_config
              FROM agents
             WHERE memory_config IS NOT NULL
            """
        )
    ).mappings()

    for row in rows:
        raw = row["memory_config"]
        if not isinstance(raw, dict):
            continue
        if raw.get("injection_enabled") is not False:
            continue

        normalized = dict(raw)
        normalized["include_mandates"] = False
        normalized["include_guardrails"] = False
        normalized["include_references"] = False
        normalized["continuity_enabled"] = False

        if normalized == raw:
            continue

        bind.execute(
            sa.text(
                """
                UPDATE agents
                   SET memory_config = CAST(:memory_config AS JSON)
                 WHERE id = :agent_id
                """
            ),
            {
                "agent_id": row["id"],
                "memory_config": json.dumps(normalized),
            },
        )


def downgrade() -> None:
    """Irreversible data canonicalization."""
