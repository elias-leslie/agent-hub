"""Tests for agent-specific tool registries."""

from __future__ import annotations

from app.services.tools.tool_definitions import get_agent_tool_specs


def test_governance_auditor_tool_registry_includes_governance_surfaces() -> None:
    tools = get_agent_tool_specs("governance-auditor")

    assert tools is not None
    tool_names = {tool.name for tool in tools}

    assert tool_names == {
        "bash",
        "read_file",
        "edit_file",
        "write_file",
        "search_scratch_context",
    }


def test_memory_curator_has_no_active_tool_registration() -> None:
    assert get_agent_tool_specs("memory-curator") is None


def test_persona_tool_registry_stays_shell_first() -> None:
    tools = get_agent_tool_specs("persona")

    assert tools is not None
    tool_names = {tool.name for tool in tools}

    assert tool_names == {
        "bash",
        "read_file",
        "edit_file",
        "write_file",
        "search_scratch_context",
    }
