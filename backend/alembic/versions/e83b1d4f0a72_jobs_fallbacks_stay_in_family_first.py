"""Put an in-family rung ahead of the cross-family one in every jobs-* chain.

Two accounts rotate on the Gemini pool, and the rotation works — the log shows
both keys tried and benched alternately. What it cannot do is create quota:
when both projects are out on one model, every request naming it falls through.

Gemini quota is per model per project, so the rung that saves a call is a
*different Gemini model*, not a different family. Observed directly: at
17:50:14 and 17:50:17 gemini-3.8-flash was benched on both keys, and at
17:50:16 gemini-3.1-flash-lite served a comparison for the same agent.

jobs-cover listed codex/gpt-5.4-mini as its FIRST fallback, ahead of
gemini-3.7-flash, so a 3.8-flash bounce jumped straight out of the family. That
is why every cover A/B run today collapsed into two Codex drafts: jobs-cover and
jobs-cover-codex carry byte-identical prompts and the same temperature, so once
both resolved to the same model the comparison had nothing left to compare.
jobs-tailor, jobs-prep and jobs-company had the same shape.

Cross-family rungs are kept, last, for the writers: a cover letter written by
the wrong family beats no cover letter. The critics keep no cross-family rung at
all — a critic that fell back across families would silently turn a second
opinion into a first one.

gemini-3.5-flash is added where a Gemini peer belongs. It is stable, free-tier
and thinking-capable, and no jobs-* agent has ever used it, so its per-project
quota is untouched.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from alembic import op

revision = "e83b1d4f0a72"
down_revision = "c41d7b60e9a2"
branch_labels = None
depends_on = None

#: Ordered fallbacks per agent. In-family rungs first; a cross-family rung only
#: where producing *something* beats producing nothing, and always last.
_CHAINS: dict[str, list[str]] = {
    # Writers and readers on the Gemini side.
    "jobs-cover": [
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "codex/gpt-5.4-mini",
    ],
    "jobs-evaluator": [
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "codex/gpt-5.4-mini",
    ],
    "jobs-screener": [
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "codex/gpt-5.4-mini",
    ],
    "jobs-company": [
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "nvidia/deepseek-v4-flash-0731",
        "zhipu/glm-4.7-flash",
    ],
    # Writers on the Codex side. codex/gpt-5.3-codex is legacy_compat and this
    # deployment authenticates through the OAuth subscription, so the peers that
    # can actually serve are 5.4 and 5.5.
    "jobs-tailor": [
        "codex/gpt-5.4",
        "codex/gpt-5.5",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
    ],
    "jobs-prep": [
        "codex/gpt-5.4",
        "codex/gpt-5.5",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
    ],
    # Second-opinion agents. In-family only, by design.
    "jobs-critic-gemini": ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"],
    "jobs-tailor-gemini": ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"],
    "jobs-critic-codex": ["codex/gpt-5.4", "codex/gpt-5.5"],
    "jobs-evaluator-codex": ["codex/gpt-5.4", "codex/gpt-5.5"],
    "jobs-cover-codex": ["codex/gpt-5.4", "codex/gpt-5.5"],
}

#: What each chain was before, so the downgrade is exact rather than a guess.
_PREVIOUS: dict[str, list[str]] = {
    "jobs-cover": ["codex/gpt-5.4-mini", "gemini-3.7-flash", "nvidia/deepseek-v4-flash-0731"],
    "jobs-evaluator": ["gemini-3.7-flash", "codex/gpt-5.4-mini", "gemini-3.1-flash-lite"],
    "jobs-screener": ["gemini-3.7-flash", "gemini-3.1-flash-lite", "codex/gpt-5.4-mini"],
    "jobs-company": [
        "nvidia/deepseek-v4-flash-0731",
        "zhipu/glm-4.7-flash",
        "gemini-3.7-flash",
        "codex/gpt-5.4-mini",
    ],
    "jobs-tailor": ["gemini-3.8-flash", "gemini-3.7-flash", "nvidia/deepseek-v4-flash-0731"],
    "jobs-prep": ["gemini-3.8-flash", "gemini-3.7-flash"],
    "jobs-critic-gemini": ["gemini-3.7-flash", "gemini-3.1-flash-lite"],
    "jobs-tailor-gemini": ["gemini-3.7-flash", "gemini-3.1-flash-lite"],
    "jobs-critic-codex": ["codex/gpt-5.3-codex", "codex/gpt-5.4"],
    "jobs-evaluator-codex": ["codex/gpt-5.3-codex", "codex/gpt-5.4"],
    "jobs-cover-codex": ["codex/gpt-5.3-codex", "codex/gpt-5.4"],
}

_UPDATE = text("UPDATE agents SET fallback_models = CAST(:chain AS JSON) WHERE slug = :slug")


def _apply(chains: dict[str, list[str]]) -> None:
    bind = op.get_bind()
    for slug, chain in chains.items():
        bind.execute(_UPDATE, {"slug": slug, "chain": json.dumps(chain)})


def upgrade() -> None:
    _apply(_CHAINS)


def downgrade() -> None:
    _apply(_PREVIOUS)
