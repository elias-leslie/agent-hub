"""Guardrails for the exported seed agent model policy."""

from __future__ import annotations

import json
from pathlib import Path

from tests.model_ids import MODEL_CATALOG

SUBSCRIPTION_ONLY_SLUGS = {
    "learn-planner", "learn-researcher", "learn-reviewer", "learn-tutor",
}

# Exact owner-promoted routes supersede the older provider-diversity policy.
# Other text agents continue to require their provider-diverse model chains.
GPT61_PROMOTED_EFFORTS = {
    "coder": "medium",
    "debugger": "high",
    "optimizer": "high",
    "refactor": "medium",
    "test-writer": "medium",
    "verifier": "high",
    "ux-polisher": "medium",
    "researcher": "medium",
    "neri-reporter": "medium",
}

EXCLUDED_SLUGS = {
    "designer",
    "graphify-semantic-extractor",
    "image-gen",
    "gemma-local-test",
    "game-art-critic-gemma",
    "market-pulse-scout",
    "game-art-critic",  # visual critique agent; see the design-critic route test
    "ui-mockup-designer",
    "game-audio-critic",  # audio input requires an audio-capable model chain
    "ux-polisher",
    "neri-hunter",  # Neri bounty roles retain explicit subscription-only routing
    "neri-reporter",
    "neri-reviewer",
    "neri-reviewer-claude",  # fallback-free Opus 5.5 review lane; see the Opus placement test
    "provider-liveness-probe",  # probe must not conceal provider failure via fallback
    # Explicit comparison/critic lanes retain provider identity.
    "jobs-cover-codex",
    "jobs-critic-codex",
    "jobs-critic-gemini",
    "jobs-evaluator-codex",
    "jobs-tailor-gemini",
    "household-receipt-vision",  # vision extraction; not a text-agent subscription policy
}
# xAI runs only when the owner explicitly requests it.
GROK_ALLOWED_SLUGS: set[str] = set()
# Visual design work leads with Claude (CLI subscription) and falls back to Codex.
CLAUDE_FIRST_DESIGN_SLUGS = {"designer", "ui-mockup-designer", "game-art-critic"}
SEED_FILE = Path(__file__).resolve().parents[2] / "scripts" / "seed_agents_data" / "seed_data.json"


def test_seed_agents_use_provider_diverse_model_chains_for_text_agents() -> None:
    data = json.loads(SEED_FILE.read_text())
    agents = data["agents"]

    assert agents, "seed_data.json should export at least one agent"

    for agent in agents:
        slug = agent["slug"]
        if slug in GPT61_PROMOTED_EFFORTS:
            assert agent["primary_model_id"] == "codex/gpt-6.1-sol", slug
            assert agent["thinking_level"] == GPT61_PROMOTED_EFFORTS[slug], slug
            assert agent["fallback_models"] == [], slug
            assert agent.get("escalation_model_id") is None, slug
            continue
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
        assert any(model.startswith("codex/") for model in model_chain), (
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


def test_design_agents_lead_with_claude_then_codex() -> None:
    data = json.loads(SEED_FILE.read_text())
    agents = {agent["slug"]: agent for agent in data["agents"]}
    for slug in CLAUDE_FIRST_DESIGN_SLUGS & agents.keys():
        agent = agents[slug]
        assert agent["primary_model_id"].startswith("claude-"), slug
        assert agent["fallback_models"][0].startswith("codex/"), slug


# Owner policy: Claude Fable 5.1 is never routable (primary, fallback or escalation).
FORBIDDEN_MODELS = {"claude-fable-5-1"}


def test_no_agent_routes_to_forbidden_models() -> None:
    data = json.loads(SEED_FILE.read_text())
    for agent in data["agents"]:
        route = {agent["primary_model_id"], *agent.get("fallback_models", []), agent.get("escalation_model_id")}
        assert not route & FORBIDDEN_MODELS, agent["slug"]
    seeded = {entry.id for entry in MODEL_CATALOG}
    assert not seeded & FORBIDDEN_MODELS, "the insert-only seed catalog must not recreate an active row"


# Opus 5.5 shares the owner's Max limits with interactive use: one dedicated
# defensive-security review lane, otherwise last-resort escalation only.
OPUS = "claude-opus-5-5"
OPUS_ESCALATION_SLUGS = {"financial-document-reviewer", "investment-committee", "risk-manager"}


def test_opus_is_placed_sparingly() -> None:
    data = json.loads(SEED_FILE.read_text())
    agents = {agent["slug"]: agent for agent in data["agents"]}
    if "neri-reviewer-claude" in agents:
        reviewer = agents["neri-reviewer-claude"]
        assert reviewer["primary_model_id"] == OPUS
        assert reviewer["fallback_models"] == [] and not reviewer.get("escalation_model_id")
        assert reviewer["memory_config"] == agents["neri-reviewer"]["memory_config"]
    for slug in OPUS_ESCALATION_SLUGS & agents.keys():
        assert agents[slug]["escalation_model_id"] == OPUS, slug
        assert OPUS not in [agents[slug]["primary_model_id"], *agents[slug]["fallback_models"]], slug
    primaries = {slug for slug, agent in agents.items() if agent["primary_model_id"] == OPUS}
    escalations = {slug for slug, agent in agents.items() if agent.get("escalation_model_id") == OPUS}
    fallbacks = {slug for slug, agent in agents.items() if OPUS in agent.get("fallback_models", [])}
    assert primaries <= {"neri-reviewer-claude"}
    assert escalations == OPUS_ESCALATION_SLUGS & agents.keys()
    assert not fallbacks


