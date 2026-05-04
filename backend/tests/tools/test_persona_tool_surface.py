from __future__ import annotations

from app.services.tools.persona_tool_surface import (
    get_persona_operator_tools_for_tier,
    get_persona_runtime_tools_for_tier,
    get_persona_runtime_tools_for_visible_tools,
    normalize_persona_tool_tier,
)


def test_persona_runtime_tool_contract_uses_project_visible_surface() -> None:
    assert get_persona_runtime_tools_for_tier("off") == ()

    read_tools = get_persona_runtime_tools_for_tier("read")
    assert read_tools[:3] == ("read_file", "search_scratch_context", "consult_agent")
    assert "query_sessions" in read_tools
    assert "inspect_session" in read_tools
    assert "dispatch_agent" not in read_tools
    assert "bash" not in read_tools

    write_tools = get_persona_runtime_tools_for_tier("write")
    assert "write_file" in write_tools
    assert "query_sessions" in write_tools
    assert "dispatch_agent" not in write_tools
    assert "bash" not in write_tools

    yolo_tools = get_persona_runtime_tools_for_tier("yolo")
    assert yolo_tools[:6] == (
        "bash",
        "read_file",
        "write_file",
        "search_scratch_context",
        "batch_execute",
        "consult_agent",
    )
    assert "dispatch_agent" in yolo_tools
    assert "manage_tasks" in yolo_tools


def test_persona_operator_tool_contract_uses_runtime_tool_names() -> None:
    assert get_persona_operator_tools_for_tier("off") == ()
    assert "read_file" in get_persona_operator_tools_for_tier("read")
    assert "write_file" in get_persona_operator_tools_for_tier("write")
    assert "dispatch_agent" in get_persona_operator_tools_for_tier("yolo")
    assert "Read" not in get_persona_operator_tools_for_tier("yolo")


def test_persona_tool_tier_fails_closed_for_unknown_values() -> None:
    assert normalize_persona_tool_tier(None) == "off"
    assert normalize_persona_tool_tier("") == "off"
    assert normalize_persona_tool_tier("admin") == "off"


def test_persona_visible_tool_filter_preserves_project_visible_persona_tools() -> None:
    assert get_persona_runtime_tools_for_visible_tools(
        {
            "read_file",
            "query_sessions",
            "inspect_session",
            "review_improvement_signals",
        }
    ) == (
        "read_file",
        "inspect_session",
        "review_improvement_signals",
        "query_sessions",
    )
