"""Guardrails for the exported seed agent model policy."""

from __future__ import annotations

import json
from pathlib import Path

from app.constants.catalog_entries import MODEL_CATALOG

SUBSCRIPTION_ONLY_SLUGS = {"learn-planner", "learn-researcher", "learn-reviewer", "learn-tutor", "neri-orchestrator"}

EXCLUDED_SLUGS = {
    "designer",
    "graphify-semantic-extractor",
    "image-gen",
    "gemma-local-test",
    "game-art-critic-gemma",
    "kimi-code-test",
    "market-pulse-scout",
    "minimax-plan-test",
    "game-art-critic",  # visual critique agent; model panel chosen by image-critique evals
    "game-audio-critic",  # audio input requires an audio-capable model chain
    "ux-polisher",
    "neri-hunter",  # controlled lab comparisons require explicit subscription-only routing
    "neri-reviewer",
    "provider-liveness-probe",  # probe must not conceal provider failure via fallback
    # Explicit comparison/critic lanes retain provider identity.
    "jobs-cover-codex",
    "jobs-critic-codex",
    "jobs-critic-gemini",
    "jobs-evaluator-codex",
    "jobs-tailor-gemini",
    "household-receipt-vision",  # vision extraction; not a text-agent subscription policy
}
GROK_ALLOWED_SLUGS = {
    "game-art-critic",  # tested as best current image critique primary
}
SEED_FILE = Path(__file__).resolve().parents[2] / "scripts" / "seed_agents_data" / "seed_data.json"


def test_seed_agents_use_provider_diverse_model_chains_for_text_agents() -> None:
    data = json.loads(SEED_FILE.read_text())
    agents = data["agents"]

    assert agents, "seed_data.json should export at least one agent"

    for agent in agents:
        slug = agent["slug"]
        if slug in SUBSCRIPTION_ONLY_SLUGS:
            assert agent["primary_model_id"].startswith("codex/")
            assert all(model.startswith("codex/") for model in agent.get("fallback_models", []))
            assert not agent.get("escalation_model_id") or agent["escalation_model_id"].startswith("codex/")
            continue
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
        if agent["slug"] in GROK_ALLOWED_SLUGS:
            continue
        models = [agent["primary_model_id"], *agent.get("fallback_models", [])]
        grok_models = [model for model in models if "xai/" in model or "grok" in model]

        assert not grok_models, f"{agent['slug']} should not use Grok/xAI by default: {grok_models}"


def test_game_audio_critic_has_audio_capable_quota_fallback() -> None:
    data = json.loads(SEED_FILE.read_text())
    audio_critic = next(agent for agent in data["agents"] if agent["slug"] == "game-audio-critic")

    assert audio_critic["primary_model_id"] == "gemini-3.5-flash"
    entries = {entry.id: entry for entry in MODEL_CATALOG}
    assert any(
        model in entries and entries[model].capabilities.supports_audio
        for model in audio_critic["fallback_models"]
    ), "Audio critique needs an audio-capable quota fallback"



def test_neri_labs_preserve_explicit_subscription_only_routes() -> None:
    data = json.loads(SEED_FILE.read_text())
    roles = {agent["slug"]: agent for agent in data["agents"] if agent["slug"] in {"neri-hunter", "neri-reviewer"}}
    assert set(roles) == {"neri-hunter", "neri-reviewer"}
    for agent in roles.values():
        assert agent["primary_model_id"].startswith("codex/")
        assert not agent.get("fallback_models")
        assert not agent.get("escalation_model_id")
