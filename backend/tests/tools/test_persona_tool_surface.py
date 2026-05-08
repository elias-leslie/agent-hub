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
    assert read_tools == ("read_file",)
    assert "query_sessions" not in read_tools
    assert "inspect_session" not in read_tools
    assert "dispatch_agent" not in read_tools
    assert "bash" not in read_tools

    full_tools = get_persona_runtime_tools_for_tier("full")
    assert full_tools == (
        "bash",
        "read_file",
        "edit_file",
        "write_file",
        "search_scratch_context",
    )
    assert "dispatch_agent" not in full_tools
    assert "manage_tasks" not in full_tools

    assert get_persona_runtime_tools_for_tier("write") == full_tools
    assert get_persona_runtime_tools_for_tier("yolo") == full_tools


def test_persona_operator_tool_contract_uses_runtime_tool_names() -> None:
    assert get_persona_operator_tools_for_tier("off") == ()
    assert "read_file" in get_persona_operator_tools_for_tier("read")
    assert "write_file" in get_persona_operator_tools_for_tier("full")
    assert "dispatch_agent" not in get_persona_operator_tools_for_tier("full")
    assert "Read" not in get_persona_operator_tools_for_tier("full")


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
    ) == ("read_file",)
