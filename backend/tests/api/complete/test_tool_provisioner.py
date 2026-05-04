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


def test_persona_read_tier_keeps_visible_hot_tools_and_deferred_catalog_access() -> None:
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
        },
    )

    loaded_names = [tool["name"] for tool in result.loaded_tools]

    assert "read_file" in loaded_names
    assert "query_sessions" in loaded_names
    assert "inspect_session" in loaded_names
    assert "tool_search" in loaded_names
    assert "tool_catalog" in loaded_names
    assert "manage_tasks" not in loaded_names
    assert any(tool["name"] == "review_improvement_signals" for tool in result.catalog_tools)


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
