"""Give utility agents a Codex subscription fallback.

Revision ID: ac0650fc9388
Revises: f35aa7ed2c9a

401372ee292c removed the retired kimi-code and MiniMax routes from these
chains, which left them with free-tier providers only. Seed policy requires a
subscription-backed route in every text agent's chain, so codex/gpt-6-luna
(about 2-3 s on the health check, 2026-10-09) becomes the first fallback.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "ac0650fc9388"
down_revision: str | Sequence[str] | None = "f35aa7ed2c9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LUNA = "codex/gpt-6-luna"
_FAST = ["cloudflare/glm-4.7-flash", "nvidia/nemotron-3-super-120b-a12b", "local/gemma4:12b-it-qat"]
_VOICE = ["gemini-3.7-flash", "cloudflare/gpt-oss-120b", "local/gemma4:12b-it-qat"]
_FAST_SLUGS = (
    "complexity-assessor", "context-compactor", "equity-analyst", "explorer", "git-agent",
    "ideator", "ideator-public", "learning-extractor", "memory-rater", "note-formatter",
    "note-titler", "summarizer", "task-sweep-orchestrator", "tester", "triager", "validator",
)
# slug: (previous fallbacks, new fallbacks)
_ROUTES = {
    **{slug: (_FAST, [_LUNA, *_FAST]) for slug in _FAST_SLUGS},
    "voice-responder": (_VOICE, [_LUNA, *_VOICE]),
}


def _set_routes(*, reverse: bool) -> None:
    conn = op.get_bind()
    for slug, (previous, desired) in _ROUTES.items():
        expected, target = (desired, previous) if reverse else (previous, desired)
        current = conn.execute(
            text("SELECT fallback_models FROM agents WHERE slug = :slug FOR UPDATE"), {"slug": slug}
        ).scalar_one()
        if (current or []) != expected:
            raise RuntimeError(f"Agent '{slug}' has an unknown model-migration revision")
        conn.execute(
            text("UPDATE agents SET fallback_models = CAST(:fallbacks AS JSON), version = version + 1, updated_at = NOW() WHERE slug = :slug"),
            {"slug": slug, "fallbacks": json.dumps(target)},
        )


def upgrade() -> None:
    _set_routes(reverse=False)


def downgrade() -> None:
    _set_routes(reverse=True)
