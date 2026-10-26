"""Tests for seed export normalization helpers."""

from types import SimpleNamespace

from scripts.export_seeds import _normalized_seed_payload, _serialize_agent, _serialize_prompt


def test_serialize_agent_keeps_agent_names() -> None:
    agent = SimpleNamespace(
        slug="coder",
        name="Code Generator",
        description="Writes code",
        system_prompt="You are a coder.",
        primary_model_id="codex/gpt-5.4",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
        thinking_level="medium",
        is_coding_agent=True,
        memory_config=None,
        max_concurrency=1,
    )

    exported = _serialize_agent(agent, None)

    assert exported["name"] == "Code Generator"
    assert exported["max_concurrency"] == 1


def test_normalized_seed_payload_ignores_generated_at() -> None:
    original = {
        "_metadata": {
            "generated_at": "2026-03-21T04:30:31.838573+00:00",
            "generator": "scripts/export_seeds.py",
            "agent_count": 36,
        },
        "agents": [{"slug": "coder"}],
        "deactivate_slugs": ["worker"],
    }
    regenerated = {
        "_metadata": {
            "generated_at": "2026-03-22T01:02:03.000000+00:00",
            "generator": "scripts/export_seeds.py",
            "agent_count": 36,
        },
        "agents": [{"slug": "coder"}],
        "deactivate_slugs": ["worker"],
    }

    assert _normalized_seed_payload(original) == _normalized_seed_payload(regenerated)


def test_serialize_prompt_preserves_owner_slug() -> None:
    prompt = SimpleNamespace(
        slug="workspace-search-discipline",
        name="Workspace Search Discipline",
        content="Use routing catalog.",
        description="Routing help",
        is_global=True,
        enabled=True,
        exclude_agents=[],
        prompt_type="standard",
        deletion_locked=False,
    )

    exported = _serialize_prompt(prompt, "coder")

    assert exported["slug"] == "workspace-search-discipline"
    assert exported["owner_agent_slug"] == "coder"
    assert exported["is_global"] is True


def test_published_seed_contains_only_public_slugs() -> None:
    import json

    from scripts.export_seeds import PUBLIC_AGENT_SLUGS, PUBLIC_PROMPT_SLUGS, SEED_FILE

    data = json.loads(SEED_FILE.read_text())
    assert {agent["slug"] for agent in data["agents"]} <= PUBLIC_AGENT_SLUGS
    assert {prompt["slug"] for prompt in data["prompts"]} <= PUBLIC_PROMPT_SLUGS
    for assignment in data["agent_prompt_assignments"]:
        assert assignment["agent_slug"] in PUBLIC_AGENT_SLUGS
        assert assignment["prompt_slug"] in PUBLIC_PROMPT_SLUGS
