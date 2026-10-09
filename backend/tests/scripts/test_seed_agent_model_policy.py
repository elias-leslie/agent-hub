"""Guardrails for the exported seed agent model policy."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from app.constants.catalog_entries import MODEL_CATALOG

SUBSCRIPTION_ONLY_SLUGS = {
    "learn-planner", "learn-researcher", "learn-reviewer", "learn-tutor",
}

# Exact owner-promoted routes supersede the older provider-diversity policy.
# Other text agents continue to require their provider-diverse model chains.
GPT61_PROMOTED_EFFORTS = {
    "coder": "medium",
    "debugger": "high",
    "fixer": "medium",
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
    "kimi-code-test",
    "market-pulse-scout",
    "minimax-plan-test",
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
    for slug in CLAUDE_FIRST_DESIGN_SLUGS:
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
    reviewer = agents["neri-reviewer-claude"]
    assert reviewer["primary_model_id"] == OPUS
    assert reviewer["fallback_models"] == [] and not reviewer.get("escalation_model_id")
    assert reviewer["memory_config"] == agents["neri-reviewer"]["memory_config"]
    for slug in OPUS_ESCALATION_SLUGS:
        assert agents[slug]["escalation_model_id"] == OPUS, slug
        assert OPUS not in [agents[slug]["primary_model_id"], *agents[slug]["fallback_models"]], slug
    primaries = {slug for slug, agent in agents.items() if agent["primary_model_id"] == OPUS}
    escalations = {slug for slug, agent in agents.items() if agent.get("escalation_model_id") == OPUS}
    fallbacks = {slug for slug, agent in agents.items() if OPUS in agent.get("fallback_models", [])}
    assert primaries == {"neri-reviewer-claude"}
    assert escalations == OPUS_ESCALATION_SLUGS
    assert not fallbacks


def test_memory_curator_is_retired_from_seeded_agents() -> None:
    data = json.loads(SEED_FILE.read_text())
    assert all(agent["slug"] != "memory-curator" for agent in data["agents"])
    assert "memory-curator" in data["deactivate_slugs"]


def test_game_audio_critic_has_audio_capable_quota_fallback() -> None:
    data = json.loads(SEED_FILE.read_text())
    audio_critic = next(agent for agent in data["agents"] if agent["slug"] == "game-audio-critic")

    entries = {entry.id: entry for entry in MODEL_CATALOG}
    assert entries[audio_critic["primary_model_id"]].capabilities.supports_audio
    assert any(
        model in entries and entries[model].capabilities.supports_audio
        for model in audio_critic["fallback_models"]
    ), "Audio critique needs an audio-capable quota fallback"



def test_neri_bounty_roles_preserve_explicit_subscription_only_routes() -> None:
    data = json.loads(SEED_FILE.read_text())
    roles = {
        agent["slug"]: agent
        for agent in data["agents"]
        if agent["slug"] in {"neri-hunter", "neri-reporter", "neri-reviewer"}
    }
    assert set(roles) == {"neri-hunter", "neri-reporter", "neri-reviewer"}
    for agent in roles.values():
        description = agent["description"].lower()
        for obsolete in ("lab", "grading-key", "training", "qualification", "cohort", "local-worker"):
            assert obsolete not in description, agent["slug"]
        assert agent["primary_model_id"].startswith("codex/")
        assert not agent.get("fallback_models")
        assert not agent.get("escalation_model_id")

    reporter = roles["neri-reporter"]
    memory = reporter["memory_config"]
    assert reporter["max_concurrency"] == 1
    assert not any(
        memory[key]
        for key in (
            "injection_enabled",
            "project_index_enabled",
            "tool_capabilities_enabled",
            "include_mandates",
            "include_guardrails",
            "include_references",
            "reference_index_enabled",
            "continuity_enabled",
        )
    )


def test_neri_seeds_cannot_restore_retired_agents_or_prompts() -> None:
    data = json.loads(SEED_FILE.read_text())
    retained_agents = {"neri-hunter", "neri-reporter", "neri-reviewer", "neri-reviewer-claude"}
    retired_agents = {"neri-local-candidate", "neri-orchestrator"}
    retired_prompts = {
        "neri-local-candidate-system-prompt",
        "neri-local-worker-routing",
        "neri-orchestrator-system-prompt",
    }
    assert {
        agent["slug"] for agent in data["agents"] if agent["slug"].startswith("neri-")
    } == retained_agents
    assert not any(
        prompt["slug"] in retired_prompts
        or prompt.get("owner_agent_slug") in retired_agents
        for prompt in data["prompts"]
    )
    assert not any(
        assignment["agent_slug"] in retired_agents
        or assignment["prompt_slug"] in retired_prompts
        for assignment in data["agent_prompt_assignments"]
    )


@pytest.mark.parametrize(("slug", "body_sha256"), [
    ("neri-hunter", "8c15f141cca20fe7b8ba995ae43cc6344f115b1eab1d6cfa8d8add321cca531f"),
    ("neri-reporter", "9b97ee17c8c6c20dcf29463bad82be197a290bbd221d2ed282a0b26d6b923d2e"),
    ("neri-reviewer", "70233a25b35713a534593ccc12c78c909d11f984d36f5d2e1c056823416a9175"),
    ("neri-reviewer-claude", "70233a25b35713a534593ccc12c78c909d11f984d36f5d2e1c056823416a9175"),
])
def test_neri_seed_bodies_match_canonical_bounty_only_previews(slug: str, body_sha256: str) -> None:
    # Exact live agent_system_prompt sections observed on 2026-10-08; do not
    # bake the inherited global prompt/context into an agent's system body.
    data = json.loads(SEED_FILE.read_text())
    body = next(agent["system_prompt"] for agent in data["agents"] if agent["slug"] == slug)
    assert sha256(body.encode()).hexdigest() == body_sha256
    if slug == "neri-reporter":
        assert "from one frozen, sanitized Neri packet" in body
        assert "Return only the caller's JSON schema" in body
    else:
        assert "`neri-records` operating boundary" in body
    assert "Never submit" in body
    for obsolete in (
        "catalog", "catalogue", "qualification", "cohort", "capture", "admission",
        "neri-research", "local-worker", "gpt-daybreak", "routing mismatch",
        "executing model", "model allowlist", "session binding",
        "training", "source_unit.events", "source_event_ids",
    ):
        assert obsolete not in body.lower()


def test_security_research_seed_keeps_neri_as_a_separate_bounty_record_system() -> None:
    data = json.loads(SEED_FILE.read_text())
    policy = next(prompt["content"] for prompt in data["prompts"] if prompt["slug"] == "security-research-operating-policy")
    assert "Neri is a separate bug-bounty hunting record system" in policy
    assert "must not be used as the store or workflow engine for general security research" in policy
    for obsolete in (
        "local-worker", "Jev", "Neri capability workflow", "fixed-denominator cohort",
        "session binding", "autonomy-proven", "transcript-first", "training-ready",
    ):
        assert obsolete not in policy
def test_portfolio_agents_prefer_codex_with_capable_gemini_fallbacks() -> None:
    data = json.loads(SEED_FILE.read_text())
    roles = {agent["slug"]: agent for agent in data["agents"]}
    entries = {entry.id: entry for entry in MODEL_CATALOG}
    for slug in ("persona", "financial-document-reviewer"):
        agent = roles[slug]
        assert agent["primary_model_id"].startswith("codex/")
        # Codex is preferred, not required. Keep the stronger Gemini route
        # ahead of the lighter route that passed the bounded grounding checks.
        assert agent["fallback_models"] == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
        for model in agent["fallback_models"]:
            assert entries[model].capabilities.supports_tool_execution
            assert entries[model].capabilities.supports_pdf
