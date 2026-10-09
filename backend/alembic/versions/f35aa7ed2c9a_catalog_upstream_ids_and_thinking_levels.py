"""Store provider upstream ids and thinking-level support in the model catalog.

Revision ID: f35aa7ed2c9a
Revises: 401372ee292c

Provider code used to hardcode model names: an upstream-id map in the model
resolver and image adapters, a Gemini prefix list for models without MINIMAL
thinking, and Codex checks for ``gpt-6.1-sol`` that also downgraded ``xhigh``
to ``high`` on every other Codex model. These now live on the catalog row, so a
model added or renamed through the catalog needs no code change.

The Codex models endpoint (2026-10-09) lists low/medium/high/xhigh, and no
minimal level, for every model; Gemini 3.7 and 3.8 Flash return HTTP 400 for
MINIMAL. Both map minimal to low.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f35aa7ed2c9a"
down_revision: str | Sequence[str] | None = "401372ee292c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPSTREAM_IDS = {
    "nvidia/nemotron-3-super-120b-a12b": "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3.5-lightning-30b-a3b": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/glm-5.3": "z-ai/glm-5.3",
    "nvidia/gpt-oss-20b": "openai/gpt-oss-20b",
    "nvidia/flux.1-dev": "black-forest-labs/flux.1-dev",
    "nvidia/flux.1-kontext-dev": "black-forest-labs/flux.1-kontext-dev",
    "cloudflare/glm-4.7-flash": "@cf/zai-org/glm-4.7-flash",
    "cloudflare/qwen3-30b": "@cf/qwen/qwen3-30b-a3b-fp8",
    "cloudflare/gpt-oss-120b": "@cf/openai/gpt-oss-120b",
    "cloudflare/gpt-oss-20b": "@cf/openai/gpt-oss-20b",
    "cloudflare/llama-4-scout-17b": "@cf/meta/llama-4-scout-17b-16e-instruct",
    "cloudflare/qwq-32b": "@cf/qwen/qwq-32b",
    "cloudflare/mistral-small-3.1-24b": "@cf/mistralai/mistral-small-3.1-24b-instruct",
    "cloudflare/qwen2.5-coder-32b": "@cf/qwen/qwen2.5-coder-32b-instruct",
    "cloudflare/gemma-4-26b": "@cf/google/gemma-4-26b-a4b-it",
    "cloudflare/granite-4.0-h-micro": "@cf/ibm-granite/granite-4.0-h-micro",
    "cloudflare/nemotron-3-120b": "@cf/nvidia/nemotron-3-120b-a12b",
    "cloudflare/flux-2-klein-9b": "@cf/black-forest-labs/flux-2-klein-9b",
    "cloudflare/flux-1-schnell": "@cf/black-forest-labs/flux-1-schnell",
    "cloudflare/sd-xl-lightning": "@cf/bytedance/stable-diffusion-xl-lightning",
    "cloudflare/leonardo-phoenix": "@cf/leonardo/phoenix-1.0",
    "cloudflare/leonardo-lucid-origin": "@cf/leonardo/lucid-origin",
}
_MINIMAL_AS_LOW = {"minimal": "low"}
_MINIMAL_AS_LOW_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "codex/gpt-6.1-sol",
    "codex/gpt-6-astra",
    "codex/gpt-6-sol",
    "codex/gpt-6-luna",
    "codex/gpt-5.6-sol",
    "codex/gpt-5.6-terra",
    "codex/gpt-5.6-luna",
    "codex/gpt-daybreak-blue-latest",
    "codex/gpt-5.5",
)


def _fill(conn, sql: str, params: dict[str, str]) -> None:
    if conn.execute(text(sql), params).rowcount != 1:
        raise RuntimeError(f"Model '{params['id']}' has an unknown model-migration revision")


def _fresh_bootstrap() -> bool:
    """True when this run builds an empty database from base (see alembic/env.py)."""
    config = getattr(op.get_context(), "config", None)
    return bool(config is not None and config.attributes.get("fresh_bootstrap"))


def upgrade() -> None:
    if _fresh_bootstrap():
        # No production data exists to transform; the seed supplies current rows.
        return
    op.add_column("models", sa.Column("thinking_level_map", postgresql.JSONB(), nullable=True))
    op.add_column("models", sa.Column("upstream_id", sa.String(200), nullable=True))
    conn = op.get_bind()
    for model_id, upstream_id in _UPSTREAM_IDS.items():
        _fill(conn, "UPDATE models SET upstream_id = :upstream WHERE id = :id",
              {"id": model_id, "upstream": upstream_id})
    for model_id in _MINIMAL_AS_LOW_MODELS:
        _fill(conn, "UPDATE models SET thinking_level_map = CAST(:levels AS JSONB) WHERE id = :id",
              {"id": model_id, "levels": json.dumps(_MINIMAL_AS_LOW)})


def downgrade() -> None:
    op.drop_column("models", "upstream_id")
    op.drop_column("models", "thinking_level_map")
