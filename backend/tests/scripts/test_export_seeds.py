"""Tests for seed export normalization helpers."""

from types import SimpleNamespace

from scripts.export_seeds import _normalized_seed_payload, _serialize_agent, _serialize_prompt


def test_serialize_agent_normalizes_persona_name_for_seed_defaults() -> None:
    agent = SimpleNamespace(
        slug="persona",
        name="Persona",
        description="Primary persona",
        system_prompt="You are the persona.",
        primary_model_id="codex/gpt-5.4",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
        thinking_level="medium",
        is_coding_agent=False,
        memory_config=None,
    )

    exported = _serialize_agent(agent, None)

    assert exported["name"] == "Persona"


def test_serialize_agent_keeps_non_persona_names() -> None:
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
    )

    exported = _serialize_agent(agent, None)

    assert exported["name"] == "Code Generator"


def test_normalized_seed_payload_ignores_generated_at() -> None:
    original = {
        "_metadata": {
            "generated_at": "2026-03-21T04:30:31.838573+00:00",
            "generator": "scripts/export_seeds.py",
            "agent_count": 36,
        },
        "agents": [{"slug": "persona"}],
        "deactivate_slugs": ["worker"],
    }
    regenerated = {
        "_metadata": {
            "generated_at": "2026-03-22T01:02:03.000000+00:00",
            "generator": "scripts/export_seeds.py",
            "agent_count": 36,
        },
        "agents": [{"slug": "persona"}],
        "deactivate_slugs": ["worker"],
    }

    assert _normalized_seed_payload(original) == _normalized_seed_payload(regenerated)


def test_serialize_prompt_preserves_owner_slug() -> None:
    prompt = SimpleNamespace(
        slug="persona-agent-routing-catalog",
        name="Persona Agent Routing Catalog",
        content="Use routing catalog.",
        description="Routing help",
        is_global=True,
        enabled=True,
        exclude_agents=[],
        prompt_type="standard",
        deletion_locked=False,
    )

    exported = _serialize_prompt(prompt, "persona")

    assert exported["slug"] == "persona-agent-routing-catalog"
    assert exported["owner_agent_slug"] == "persona"
    assert exported["is_global"] is True
