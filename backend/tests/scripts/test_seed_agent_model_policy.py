"""Guardrails for the exported seed agent model policy."""

from __future__ import annotations

import json
from pathlib import Path

EXCLUDED_SLUGS = {"designer", "ux-polisher", "image-gen", "market-pulse-scout"}
SEED_FILE = Path(__file__).resolve().parents[2] / "scripts" / "seed_agents_data" / "seed_data.json"


def test_seed_agents_use_codex_primary_with_mixed_fallbacks_for_text_agents() -> None:
    data = json.loads(SEED_FILE.read_text())
    agents = data["agents"]

    assert agents, "seed_data.json should export at least one agent"

    for agent in agents:
        slug = agent["slug"]
        if slug in EXCLUDED_SLUGS:
            continue

        primary_model_id = agent["primary_model_id"]
        fallback_models = agent.get("fallback_models", [])

        assert primary_model_id.startswith("codex/"), f"{slug} should keep a Codex primary: {primary_model_id}"
        assert fallback_models, f"{slug} should define fallback models"
        assert len(fallback_models) == len(set(fallback_models)), f"{slug} should not contain duplicate fallbacks"
        assert any(model.startswith("codex/") for model in fallback_models), (
            f"{slug} should include a Codex fallback: {fallback_models}"
        )
        assert any(not model.startswith("codex/") for model in fallback_models), (
            f"{slug} should include a non-Codex fallback: {fallback_models}"
        )
