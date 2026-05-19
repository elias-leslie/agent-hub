"""diversify_vantage_intake_provider_chain

Revision ID: 9cff0500948a
Revises: eb674674f37b
Create Date: 2026-05-18

The ``vantage-intake`` agent's chain was also all-codex
(``codex/gpt-5.4-mini`` → ``codex/gpt-5.4`` → ``codex/gpt-5.3-codex``).
Same guardrail as ``eb674674f37b`` — every non-committee agent must
keep at least two providers so a single-provider outage doesn't strand
the routing.

Append ``gemini-3.1-flash-lite`` as the tail fallback. The agent is
not coding-heavy (it's a small structured-data intake bot), and
Gemini Flash is the cheapest second-provider option already in
production use across other non-coding agents.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "9cff0500948a"
down_revision: str | Sequence[str] | None = "eb674674f37b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_FALLBACKS = ["codex/gpt-5.4", "codex/gpt-5.3-codex"]
_NEW_FALLBACKS = ["codex/gpt-5.4", "codex/gpt-5.3-codex", "gemini-3.1-flash-lite"]


def _swap_chain(new: list[str], old: list[str]) -> None:
    op.get_bind().execute(
        text(
            "UPDATE agents SET fallback_models = CAST(:new AS jsonb) "
            "WHERE slug = 'vantage-intake' "
            "AND fallback_models::jsonb = CAST(:old AS jsonb)"
        ),
        {"new": json.dumps(new), "old": json.dumps(old)},
    )


def upgrade() -> None:
    _swap_chain(_NEW_FALLBACKS, _OLD_FALLBACKS)


def downgrade() -> None:
    _swap_chain(_OLD_FALLBACKS, _NEW_FALLBACKS)
