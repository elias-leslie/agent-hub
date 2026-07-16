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


def test_memory_curator_tool_registry_exposes_memory_review_and_workspace_tools() -> None:
    tools = get_agent_tool_specs("memory-curator")

    assert tools is not None
    tool_names = {tool.name for tool in tools}

    assert tool_names == {
        "bash",
        "read_file",
        "edit_file",
        "write_file",
        "search_scratch_context",
        "review_memory_system",
    }
    review_tool = next(tool for tool in tools if tool.name == "review_memory_system")
    assert review_tool.input_schema["properties"]["force_all"]["type"] == "boolean"
    assert review_tool.input_schema["properties"]["only_missing_compact"]["type"] == "boolean"
    assert review_tool.input_schema["properties"]["only_incomplete_audit"]["type"] == "boolean"
    assert review_tool.input_schema["properties"]["cadence_days"]["minimum"] == 0
    assert review_tool.input_schema["properties"]["batch_limit"]["maximum"] == 10


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
