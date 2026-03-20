"""Tests for seed export normalization helpers."""

from types import SimpleNamespace

from scripts.export_seeds import _serialize_agent


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
        tool_permissions=None,
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
        tool_permissions=None,
        memory_config=None,
    )

    exported = _serialize_agent(agent, None)

    assert exported["name"] == "Code Generator"
