"""diversify_refactor_agent_provider_chain

Revision ID: eb674674f37b
Revises: 7af266db1c51
Create Date: 2026-05-18

The ``refactor`` agent's model chain was all-codex
(``codex/gpt-5.5`` → ``codex/gpt-5.4``). The seed-policy guardrail
(``tests/scripts/test_seed_agent_model_policy.py``) requires every
non-committee agent to keep at least two distinct providers in the
chain so a single-provider outage cannot strand the routing.

Add ``kimi-code/kimi-for-coding`` as the secondary fallback. It is
already used by other coding agents (``planner``, ``brainstormer``)
so the route is exercised. ``codex/gpt-5.4`` is kept as the first
fallback because the agent's prompt is tuned to gpt-family behavior.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "eb674674f37b"
down_revision: str | Sequence[str] | None = "7af266db1c51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_FALLBACKS = ["codex/gpt-5.4"]
_NEW_FALLBACKS = ["codex/gpt-5.4", "kimi-code/kimi-for-coding"]


def _swap_chain(new: list[str], old: list[str]) -> None:
    # fallback_models is JSON; the equality predicate casts both sides
    # to jsonb so a site that has already hand-customized the chain is
    # left alone.
    op.get_bind().execute(
        text(
            "UPDATE agents SET fallback_models = CAST(:new AS jsonb) "
            "WHERE slug = 'refactor' "
            "AND fallback_models::jsonb = CAST(:old AS jsonb)"
        ),
        {"new": json.dumps(new), "old": json.dumps(old)},
    )


def upgrade() -> None:
    _swap_chain(_NEW_FALLBACKS, _OLD_FALLBACKS)


def downgrade() -> None:
    _swap_chain(_OLD_FALLBACKS, _NEW_FALLBACKS)
