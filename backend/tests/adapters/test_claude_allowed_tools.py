"""Tests for Claude allowed_tools surface construction."""

from app.adapters._claude_constants import build_allowed_tools


def test_build_allowed_tools_uses_only_requested_builtins() -> None:
    allowed = build_allowed_tools([
        {"name": "read_file"},
        {"name": "write_file"},
    ])

    assert allowed == ["Read", "Write", "Edit"]


def test_build_allowed_tools_includes_bash_only_when_exposed() -> None:
    allowed = build_allowed_tools([
        {"name": "bash"},
        {"name": "read_file"},
    ])

    assert allowed == ["Bash", "Read"]


def test_build_allowed_tools_adds_only_requested_mcp_tools() -> None:
    allowed = build_allowed_tools([
        {"name": "read_file"},
        {"name": "query_sessions"},
    ])

    assert allowed == ["Read", "mcp__agent-hub__query_sessions"]
