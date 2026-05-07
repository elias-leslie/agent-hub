from __future__ import annotations

from app.api.complete.tool_provisioner import provision_standard_tools


def test_provision_standard_tools_uses_minimal_shell_first_baseline() -> None:
    result = provision_standard_tools(True, None)

    assert [tool["name"] for tool in result.loaded_tools] == [
        "bash",
        "read_file",
        "write_file",
        "search_scratch_context",
    ]


def test_persona_off_tier_fails_closed_without_project_visibility() -> None:
    result = provision_standard_tools(
        True,
        None,
        agent_slug="persona",
        project_id="agent-hub",
        defer_tool_loading=True,
        visible_tool_names=frozenset(),
    )

    assert result.loaded_tools == []
    assert result.catalog_tools == []


def test_persona_read_tier_keeps_project_visible_runtime_tools_hot_loaded() -> None:
    result = provision_standard_tools(
        True,
        None,
        agent_slug="persona",
        project_id="agent-hub",
        defer_tool_loading=True,
        visible_tool_names={
            "read_file",
            "query_sessions",
            "inspect_session",
            "review_improvement_signals",
            "tool_search",
        },
    )

    loaded_names = [tool["name"] for tool in result.loaded_tools]

    assert loaded_names == ["read_file"]
    assert [tool["name"] for tool in result.catalog_tools] == ["read_file"]


def test_persona_full_tier_keeps_project_visible_runtime_tools_hot_loaded() -> None:
    result = provision_standard_tools(
        True,
        None,
        agent_slug="persona",
        project_id="agent-hub",
        defer_tool_loading=True,
        visible_tool_names={
            "read_file",
            "write_file",
            "query_sessions",
            "inspect_session",
            "review_improvement_signals",
        },
    )

    assert [tool["name"] for tool in result.loaded_tools] == [
        "read_file",
        "write_file",
    ]
    assert [tool["name"] for tool in result.catalog_tools] == [
        "read_file",
        "write_file",
    ]


def test_persona_full_tier_keeps_shell_first_tools_visible() -> None:
    result = provision_standard_tools(
        True,
        None,
        agent_slug="persona",
        project_id="agent-hub",
        visible_tool_names={
            "bash",
            "read_file",
            "write_file",
            "search_scratch_context",
            "dispatch_agent",
            "manage_tasks",
            "query_sessions",
        },
    )

    assert [tool["name"] for tool in result.loaded_tools] == [
        "bash",
        "read_file",
        "write_file",
        "search_scratch_context",
    ]

    assert [tool["name"] for tool in result.catalog_tools] == [
        tool["name"] for tool in result.loaded_tools
    ]


def test_memory_curator_full_tier_exposes_workspace_tools_and_memory_review() -> None:
    result = provision_standard_tools(
        True,
        None,
        agent_slug="memory-curator",
        project_id="agent-hub",
        visible_tool_names={"bash", "read_file", "write_file", "review_memory_system"},
    )

    assert [tool["name"] for tool in result.loaded_tools] == [
        "bash",
        "read_file",
        "write_file",
        "review_memory_system",
    ]
