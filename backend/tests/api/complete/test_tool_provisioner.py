from __future__ import annotations

from app.api.complete.tool_provisioner import provision_standard_tools


def test_provision_standard_tools_uses_minimal_shell_first_baseline() -> None:
    result = provision_standard_tools(True, None)

    assert [tool["name"] for tool in result.loaded_tools] == [
        "bash",
        "read_file",
        "write_file",
    ]


def test_persona_read_tier_hides_runtime_denied_operational_tools() -> None:
    result = provision_standard_tools(
        True,
        None,
        agent_slug="persona",
        project_id="agent-hub",
        visible_tool_names={"read_file"},
    )

    assert [tool["name"] for tool in result.loaded_tools] == ["read_file"]


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
