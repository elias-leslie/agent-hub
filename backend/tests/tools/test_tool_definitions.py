"""Tests for agent-specific tool registries."""

from __future__ import annotations

from app.services.tools.tool_definitions import get_agent_tool_specs


def test_governance_auditor_tool_registry_includes_governance_surfaces() -> None:
    tools = get_agent_tool_specs("governance-auditor")

    assert tools is not None
    tool_names = {tool.name for tool in tools}

    assert "bash" in tool_names
    assert "read_file" in tool_names
    assert "precision_code_search" in tool_names
    assert "manage_feedback" in tool_names
    assert "query_sessions" in tool_names
    assert "inspect_session" in tool_names
    assert "read_heartbeat_instructions" in tool_names


def test_memory_curator_tool_registry_exposes_single_review_surface() -> None:
    tools = get_agent_tool_specs("memory-curator")

    assert tools is not None
    tool_names = {tool.name for tool in tools}

    assert tool_names == {"review_memory_system"}


def test_persona_tool_registry_includes_memory_review_surface() -> None:
    tools = get_agent_tool_specs("persona")

    assert tools is not None
    tool_names = {tool.name for tool in tools}

    assert "review_memory_system" in tool_names
