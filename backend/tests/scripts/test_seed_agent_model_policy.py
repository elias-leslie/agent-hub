"""Guardrails for the exported seed agent model policy."""

from __future__ import annotations

import json
from pathlib import Path

EXCLUDED_SLUGS = {
    "designer",
    "graphify-semantic-extractor",
    "image-gen",
    "gemma-local-test",
    "kimi-code-test",
    "market-pulse-scout",
    "minimax-plan-test",
    "ux-polisher",
}
SEED_FILE = Path(__file__).resolve().parents[2] / "scripts" / "seed_agents_data" / "seed_data.json"


def test_seed_agents_use_provider_diverse_model_chains_for_text_agents() -> None:
    data = json.loads(SEED_FILE.read_text())
    agents = data["agents"]

    assert agents, "seed_data.json should export at least one agent"

    for agent in agents:
        slug = agent["slug"]
        if slug in EXCLUDED_SLUGS:
            continue
        if agent.get("name", "").startswith("Committee "):
            continue

        primary_model_id = agent["primary_model_id"]
        fallback_models = agent.get("fallback_models", [])
        model_chain = [primary_model_id, *fallback_models]
        providers = {model.split("/", 1)[0] for model in model_chain}

        assert primary_model_id, f"{slug} should define a primary model"
        assert fallback_models, f"{slug} should define fallback models"
        assert len(fallback_models) == len(set(fallback_models)), f"{slug} should not contain duplicate fallbacks"
        assert len(providers) >= 2, f"{slug} should keep provider-diverse routing: {model_chain}"
        assert not any(model.startswith("claude-") for model in model_chain), (
            f"{slug} should not route Agent Hub workloads to Claude: {model_chain}"
        )
        assert any(model.startswith(("codex/", "kimi-code/", "minimax/")) for model in model_chain), (
            f"{slug} should include at least one subscription-backed route: {model_chain}"
        )


def test_seed_agents_do_not_use_grok_by_default() -> None:
    data = json.loads(SEED_FILE.read_text())

    for agent in data["agents"]:
        models = [agent["primary_model_id"], *agent.get("fallback_models", [])]
        grok_models = [model for model in models if "xai/" in model or "grok" in model]

        assert not grok_models, f"{agent['slug']} should not use Grok/xAI by default: {grok_models}"
