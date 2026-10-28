"""Register GPT-6.1 Terra on the existing provider routes.

OpenAI specs: https://developers.openai.com/api/docs/models/gpt-6.1-terra
Codex capabilities: locally advertised model list, 2026-10-28. Listing is
not proof of entitlement. Scores are inherited from 5.6 Terra, not benchmarks.
The OpenAI adapter uses Chat Completions; Terra tool calling requires Responses.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "d6a9b3c7e2f1"
down_revision = "c5e8a2b6d4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    config = getattr(op.get_context(), "config", None)
    if config is not None and config.attributes.get("fresh_bootstrap"):
        return
    conn = op.get_bind()
    models = sa.Table("models", sa.MetaData(), autoload_with=conn)
    previous = conn.execute(sa.select(models).where(models.c.id == "codex/gpt-5.6-terra")).mappings().one_or_none()
    if previous is None:
        return  # An unseeded database receives the exported catalog at startup.
    common = {k: v for k, v in previous.items() if k not in {"created_at", "updated_at"}}
    common.update(name="GPT-6.1 Terra", hint="Visual reasoning, computer use and writing; inherited scores",
                  knowledge_cutoff="2026-06-01", release_date=None, is_active=True,
                  subscription_rates=None, upstream_id=None, supports_pdf=False,
                  can_generate_images=False, can_edit_images=False, supports_audio=False)
    rows = [
        dict(common, id="codex/gpt-6.1-terra", alias="codex-gpt-6.1-terra", provider="codex",
             context_window=500000, max_output_tokens=128000, cost_input_per_m=0, cost_output_per_m=0,
             cache_read_per_million=None, cache_write_per_million=None, service_tiers={"default": 1.0},
             supports_tool_execution=True, supports_session_cache=True,
             thinking_level_map={"minimal": "low"}, access_programs={"cyber": "standard"},
             availability="codex_oauth; advertised_2026-10-28; entitlement_unverified; low_medium_high_xhigh_max_ultra"),
        dict(common, id="openai/gpt-6.1-terra", alias="gpt-6.1-terra", provider="openai",
             context_window=1050000, max_output_tokens=128000, cost_input_per_m=1, cost_output_per_m=5,
             cache_read_per_million=0.05, cache_write_per_million=1.25,
             service_tiers={"default": 1.0, "flex": 0.5, "priority": 2.0},
             supports_tool_execution=False, supports_session_cache=False,
             thinking_level_map={"minimal": "low"}, access_programs=None,
             availability="chat_completions_without_tools; api_entitlement_unverified; input_over_272k_bills_2x_input_1.5x_output"),
    ]
    aliases = sa.Table("model_aliases", sa.MetaData(), autoload_with=conn)
    for row in rows:
        existing = conn.execute(sa.select(models.c.id).where(models.c.id == row["id"])).first()
        if existing:
            raise RuntimeError(f"Catalog entry {row['id']} already exists; preserve its settings")
        conn.execute(models.insert().values(**row))
        conn.execute(aliases.insert().values(alias=row["alias"], model_id=row["id"], alias_type="canonical", source="seed"))


def downgrade() -> None:
    # Preserve identity and historical references.
    op.execute("UPDATE models SET is_active = FALSE WHERE id IN ('codex/gpt-6.1-terra', 'openai/gpt-6.1-terra')")
