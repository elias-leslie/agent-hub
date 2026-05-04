from __future__ import annotations

from app.services.tools.persona_tool_surface import (
    get_persona_operator_tools_for_tier,
    get_persona_runtime_tools_for_tier,
    get_persona_runtime_tools_for_visible_tools,
    normalize_persona_tool_tier,
)


def test_persona_runtime_tool_contract_is_fixed_by_tier() -> None:
    assert get_persona_runtime_tools_for_tier("off") == ()
    assert get_persona_runtime_tools_for_tier("read") == ("read_file",)
    assert get_persona_runtime_tools_for_tier("write") == ("read_file", "write_file")
    assert get_persona_runtime_tools_for_tier("yolo") == (
        "bash",
        "read_file",
        "write_file",
    )


def test_persona_operator_tool_contract_uses_provider_builtin_names() -> None:
    assert get_persona_operator_tools_for_tier("off") == ()
    assert get_persona_operator_tools_for_tier("read") == ("Read",)
    assert get_persona_operator_tools_for_tier("write") == ("Read", "Write", "Edit")
    assert get_persona_operator_tools_for_tier("yolo") == (
        "Read",
        "Write",
        "Edit",
        "Bash",
    )


def test_persona_tool_tier_fails_closed_for_unknown_values() -> None:
    assert normalize_persona_tool_tier(None) == "off"
    assert normalize_persona_tool_tier("") == "off"
    assert normalize_persona_tool_tier("admin") == "off"


def test_persona_visible_tool_inference_ignores_legacy_persona_extras() -> None:
    assert get_persona_runtime_tools_for_visible_tools(
        {
            "read_file",
            "query_sessions",
            "inspect_session",
            "review_improvement_signals",
        }
    ) == ("read_file",)
