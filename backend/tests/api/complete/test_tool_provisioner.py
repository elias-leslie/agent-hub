from __future__ import annotations

from app.api.complete.tool_provisioner import provision_standard_tools


def test_provision_standard_tools_uses_minimal_shell_first_baseline() -> None:
    result = provision_standard_tools(True, None)

    assert [tool["name"] for tool in result.loaded_tools] == [
        "bash",
        "read_file",
        "edit_file",
        "write_file",
        "search_scratch_context",
    ]


def test_agent_with_its_own_registry_gets_only_those_tools() -> None:
    result = provision_standard_tools(True, None, agent_slug="jobs-company", defer_tool_loading=True)

    names = ["research_web", "search_web", "fetch_web_page"]
    assert [tool["name"] for tool in result.loaded_tools] == names
    assert [tool["name"] for tool in result.catalog_tools] == names


def test_agent_without_a_registry_gets_the_standard_tools() -> None:
    result = provision_standard_tools(True, None, agent_slug="memory-curator")

    assert [tool["name"] for tool in result.loaded_tools] == [
        "bash",
        "read_file",
        "edit_file",
        "write_file",
        "search_scratch_context",
    ]
