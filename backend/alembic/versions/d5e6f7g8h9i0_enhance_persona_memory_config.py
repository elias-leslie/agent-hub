"""enhance_persona_memory_config

Revision ID: d5e6f7g8h9i0
Revises: c4d5e6f7g8h9
Create Date: 2026-02-21 23:30:00.000000

Updates the persona agent's memory_config with enhanced continuity settings:
cross_project_enabled, live_sessions_enabled, and persona-relevant tags.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d5e6f7g8h9i0"
down_revision: str | Sequence[str] | None = "c4d5e6f7g8h9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENHANCED_MEMORY_CONFIG = {
    "injection_enabled": True,
    "budget_enforcement": False,
    "token_budget": 5000,
    "max_mandates": 0,
    "max_guardrails": 0,
    "reference_index": True,
    "continuity_enabled": True,
    "continuity_max_sessions": 20,
    "cross_project_enabled": True,
    "live_sessions_enabled": True,
    "include_tags": ["persona-relevant"],
    "exclude_tags": [],
}


def upgrade() -> None:
    config_json = json.dumps(ENHANCED_MEMORY_CONFIG)
    op.get_bind().execute(
        sa.text(
            "UPDATE agents SET memory_config = CAST(:config AS JSON) WHERE slug = 'persona'"
        ),
        {"config": config_json},
    )


def downgrade() -> None:
    # Restore previous config without cross_project/live_sessions
    previous = {
        "injection_enabled": True,
        "budget_enforcement": False,
        "token_budget": 3500,
        "max_mandates": 0,
        "max_guardrails": 0,
        "reference_index": True,
        "continuity_enabled": True,
        "continuity_max_sessions": 20,
        "include_tags": [],
        "exclude_tags": [],
    }
    config_json = json.dumps(previous)
    op.get_bind().execute(
        sa.text(
            "UPDATE agents SET memory_config = CAST(:config AS JSON) WHERE slug = 'persona'"
        ),
        {"config": config_json},
    )
