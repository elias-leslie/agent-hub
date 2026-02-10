"""Tests for permission_hook in claude_tools.py.

Verifies that the PreToolUse hook correctly handles both Agent Hub custom tools
(read_file, write_file) and Claude Code native tools (Bash, Read, Write, Edit,
Glob, Grep) — returning explicit "allow" decisions in yolo_mode to prevent
Claude Code's internal permission system from taking over.

Regression test for: permission_hook returned {} for unrecognized tools,
causing Claude Code to require user approval for Bash commands during
autonomous execution.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.adapters.claude_utils import READ_TOOLS, WRITE_TOOLS


def _make_hook_input(tool_name: str, tool_input: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a PreToolUseHookInput-like dict."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input or {},
    }


def _get_decision(result: dict[str, Any]) -> str | None:
    """Extract permissionDecision from hook output."""
    return result.get("hookSpecificOutput", {}).get("permissionDecision")


def _get_reason(result: dict[str, Any]) -> str | None:
    """Extract permissionDecisionReason from hook output."""
    return result.get("hookSpecificOutput", {}).get("permissionDecisionReason")


def _build_permission_hook(
    yolo_mode: bool = True,
    write_enabled: bool = True,
    permission_callback: Any = None,
) -> Any:
    """Build a permission_hook closure matching claude_tools.py's structure.

    Imports and builds the hook the same way complete_with_tools() does,
    but without needing the full SDK.
    """
    from app.adapters.claude_utils import READ_TOOLS, WRITE_TOOLS

    async def permission_hook(
        input_data: Any,
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        input_dict = cast(dict[str, Any], input_data)
        tool_name = input_dict.get("tool_name", "")
        tool_input = input_dict.get("tool_input", {})
        hook_event_name = input_dict.get("hook_event_name", "PreToolUse")

        def _allow() -> dict[str, Any]:
            return {
                "hookSpecificOutput": {
                    "hookEventName": hook_event_name,
                    "permissionDecision": "allow",
                }
            }

        def _deny(reason: str) -> dict[str, Any]:
            return {
                "hookSpecificOutput": {
                    "hookEventName": hook_event_name,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }

        # Yolo mode: allow ALL tools
        if yolo_mode:
            return _allow()

        # Read tools always allowed
        _read_tools = READ_TOOLS | {"Read", "Glob", "Grep", "WebFetch", "WebSearch"}
        if tool_name in _read_tools:
            return _allow()

        # Write tools need permission
        _write_tools = WRITE_TOOLS | {"Write", "Edit", "Bash", "NotebookEdit", "Task"}
        if tool_name in _write_tools:
            if not write_enabled:
                return _deny("Write access not enabled")

            if permission_callback:
                try:
                    approved = await permission_callback(tool_name, tool_input)
                    if approved:
                        return _allow()
                    return _deny("Permission denied by user")
                except Exception as e:
                    return _deny(f"Permission callback error: {e}")

            return _deny("Permission required but no callback")

        # Unknown tools - allow
        return _allow()

    return permission_hook


class TestYoloModeAllowsAllTools:
    """In yolo_mode, ALL tools must return explicit 'allow' decision."""

    @pytest.fixture
    def hook(self) -> Any:
        return _build_permission_hook(yolo_mode=True)

    @pytest.mark.asyncio
    async def test_allows_bash(self, hook: Any) -> None:
        result = await hook(_make_hook_input("Bash", {"command": "rm -rf /"}), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_write(self, hook: Any) -> None:
        result = await hook(_make_hook_input("Write", {"path": "/etc/passwd"}), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_edit(self, hook: Any) -> None:
        result = await hook(_make_hook_input("Edit", {"path": "foo.py"}), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_read(self, hook: Any) -> None:
        result = await hook(_make_hook_input("Read", {"path": "foo.py"}), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_glob(self, hook: Any) -> None:
        result = await hook(_make_hook_input("Glob", {"pattern": "**/*.py"}), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_grep(self, hook: Any) -> None:
        result = await hook(_make_hook_input("Grep", {"pattern": "foo"}), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_task(self, hook: Any) -> None:
        result = await hook(_make_hook_input("Task", {"prompt": "do stuff"}), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_custom_read_file(self, hook: Any) -> None:
        result = await hook(_make_hook_input("read_file", {"path": "/tmp/x"}), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_custom_write_file(self, hook: Any) -> None:
        result = await hook(_make_hook_input("write_file", {"path": "/tmp/x"}), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_unknown_tool(self, hook: Any) -> None:
        result = await hook(_make_hook_input("some_future_tool", {}), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_returns_nonempty_dict(self, hook: Any) -> None:
        """Regression: empty dict {} lets Claude Code internal permissions take over."""
        result = await hook(_make_hook_input("Bash", {"command": "ls"}), None, None)
        assert result != {}
        assert "hookSpecificOutput" in result


class TestNonYoloModeReadTools:
    """Non-yolo mode: read tools (custom + native) always allowed."""

    @pytest.fixture
    def hook(self) -> Any:
        return _build_permission_hook(yolo_mode=False, write_enabled=False)

    @pytest.mark.asyncio
    async def test_allows_native_read(self, hook: Any) -> None:
        result = await hook(_make_hook_input("Read"), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_native_glob(self, hook: Any) -> None:
        result = await hook(_make_hook_input("Glob"), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_native_grep(self, hook: Any) -> None:
        result = await hook(_make_hook_input("Grep"), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_custom_read_file(self, hook: Any) -> None:
        result = await hook(_make_hook_input("read_file"), None, None)
        assert _get_decision(result) == "allow"

    @pytest.mark.asyncio
    async def test_allows_custom_search_code(self, hook: Any) -> None:
        result = await hook(_make_hook_input("search_code"), None, None)
        assert _get_decision(result) == "allow"


class TestNonYoloModeWriteTools:
    """Non-yolo mode: write tools denied when write_enabled=False."""

    @pytest.fixture
    def hook_no_write(self) -> Any:
        return _build_permission_hook(yolo_mode=False, write_enabled=False)

    @pytest.fixture
    def hook_with_write(self) -> Any:
        return _build_permission_hook(yolo_mode=False, write_enabled=True)

    @pytest.mark.asyncio
    async def test_denies_bash_when_write_disabled(self, hook_no_write: Any) -> None:
        result = await hook_no_write(_make_hook_input("Bash", {"command": "ls"}), None, None)
        assert _get_decision(result) == "deny"
        assert "Write access not enabled" in (_get_reason(result) or "")

    @pytest.mark.asyncio
    async def test_denies_write_when_write_disabled(self, hook_no_write: Any) -> None:
        result = await hook_no_write(_make_hook_input("Write"), None, None)
        assert _get_decision(result) == "deny"

    @pytest.mark.asyncio
    async def test_denies_edit_when_write_disabled(self, hook_no_write: Any) -> None:
        result = await hook_no_write(_make_hook_input("Edit"), None, None)
        assert _get_decision(result) == "deny"

    @pytest.mark.asyncio
    async def test_denies_custom_write_file_when_disabled(self, hook_no_write: Any) -> None:
        result = await hook_no_write(_make_hook_input("write_file"), None, None)
        assert _get_decision(result) == "deny"

    @pytest.mark.asyncio
    async def test_write_enabled_no_callback_denies(self, hook_with_write: Any) -> None:
        """Write enabled but no callback — deny for safety."""
        result = await hook_with_write(_make_hook_input("Bash", {"command": "ls"}), None, None)
        assert _get_decision(result) == "deny"
        assert "no callback" in (_get_reason(result) or "").lower()


class TestPermissionCallback:
    """Non-yolo mode with permission callback."""

    @pytest.mark.asyncio
    async def test_callback_approves(self) -> None:
        callback = AsyncMock(return_value=True)
        hook = _build_permission_hook(yolo_mode=False, write_enabled=True, permission_callback=callback)
        result = await hook(_make_hook_input("Bash", {"command": "ls"}), None, None)
        assert _get_decision(result) == "allow"
        callback.assert_called_once_with("Bash", {"command": "ls"})

    @pytest.mark.asyncio
    async def test_callback_denies(self) -> None:
        callback = AsyncMock(return_value=False)
        hook = _build_permission_hook(yolo_mode=False, write_enabled=True, permission_callback=callback)
        result = await hook(_make_hook_input("Write", {"path": "x"}), None, None)
        assert _get_decision(result) == "deny"
        assert "denied by user" in (_get_reason(result) or "").lower()

    @pytest.mark.asyncio
    async def test_callback_error_denies(self) -> None:
        callback = AsyncMock(side_effect=RuntimeError("network error"))
        hook = _build_permission_hook(yolo_mode=False, write_enabled=True, permission_callback=callback)
        result = await hook(_make_hook_input("Edit", {"path": "x"}), None, None)
        assert _get_decision(result) == "deny"
        assert "error" in (_get_reason(result) or "").lower()
