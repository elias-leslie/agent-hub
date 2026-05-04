from __future__ import annotations

from app.api.complete.tool_provisioner import provision_standard_tools


def test_provision_standard_tools_uses_minimal_shell_first_baseline() -> None:
    result = provision_standard_tools(True, None)

    assert [tool["name"] for tool in result.loaded_tools] == [
        "bash",
        "read_file",
        "write_file",
        "search_scratch_context",
        "batch_execute",
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


def test_persona_read_tier_keeps_only_read_file_hot_loaded() -> None:
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


def test_persona_write_tier_keeps_only_read_write_hot_loaded() -> None:
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


def test_persona_yolo_tier_keeps_core_shell_tools_visible() -> None:
    result = provision_standard_tools(
        True,
        None,
        agent_slug="persona",
        project_id="agent-hub",
        visible_tool_names={"bash", "read_file", "write_file"},
    )

    assert [tool["name"] for tool in result.loaded_tools] == [
        "bash",
        "read_file",
        "write_file",
    ]

    assert [tool["name"] for tool in result.catalog_tools] == [
        "bash",
        "read_file",
        "write_file",
    ]


def test_memory_curator_yolo_tier_exposes_workspace_tools_and_memory_review() -> None:
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
