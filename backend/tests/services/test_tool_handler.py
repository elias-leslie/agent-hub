"""Tests for tool_handler — fail-closed permission hook behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.tools.base import ToolCall, ToolDecision
from app.services.tools.tool_handler import (
    DirectToolHandler,
    _compose_hooks,
    _create_project_permission_hook,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call(name: str = "read_file") -> ToolCall:
    """Create a minimal ToolCall for testing."""
    return ToolCall(id="test-id", name=name, input={})


# ---------------------------------------------------------------------------
# _create_project_permission_hook fail-closed tests
# ---------------------------------------------------------------------------


class TestProjectPermissionHookFailClosed:
    """Verify the permission hook denies on any exception (fail-closed)."""

    @pytest.mark.asyncio
    async def test_hook_denies_when_check_tool_allowed_raises(self):
        """If check_tool_allowed raises, the hook should return DENY."""
        hook = _create_project_permission_hook("test-project")
        tool_call = _make_tool_call("bash")

        with patch(
            "app.services.project_permission_service.check_tool_allowed",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB connection failed"),
        ):
            decision = await hook(tool_call)
            assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_hook_denies_when_import_fails(self):
        """If the import inside the hook fails, should return DENY."""
        hook = _create_project_permission_hook("test-project")
        tool_call = _make_tool_call("read_file")

        with patch(
            "app.services.project_permission_service.check_tool_allowed",
            side_effect=ImportError("module not found"),
        ):
            decision = await hook(tool_call)
            assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_hook_allows_when_check_returns_allowed(self):
        """Normal path: check_tool_allowed returns (True, 'allowed')."""
        hook = _create_project_permission_hook("test-project")
        tool_call = _make_tool_call("read_file")

        with patch(
            "app.services.project_permission_service.check_tool_allowed",
            new_callable=AsyncMock,
            return_value=(True, "allowed"),
        ):
            decision = await hook(tool_call)
            assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_hook_denies_when_check_returns_denied(self):
        """Normal path: check_tool_allowed returns (False, reason)."""
        hook = _create_project_permission_hook("test-project")
        tool_call = _make_tool_call("bash")

        with patch(
            "app.services.project_permission_service.check_tool_allowed",
            new_callable=AsyncMock,
            return_value=(False, "tool 'bash' not permitted at tier 'read'"),
        ):
            decision = await hook(tool_call)
            assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_hook_forwards_tool_input_to_permission_check(self):
        """Action-aware permission checks must receive the raw tool payload."""
        hook = _create_project_permission_hook("test-project")
        tool_call = ToolCall(
            id="test-id",
            name="manage_tasks",
            input={"action": "dispatch", "task_id": "task-123"},
        )

        with patch(
            "app.services.project_permission_service.check_tool_allowed",
            new_callable=AsyncMock,
            return_value=(False, "direct helper tool disabled; use bash with st"),
        ) as mock_check:
            decision = await hook(tool_call)

        assert decision == ToolDecision.DENY
        mock_check.assert_awaited_once_with(
            "test-project", "manage_tasks", tool_input=tool_call.input,
        )


# ---------------------------------------------------------------------------
# _compose_hooks fail-closed tests
# ---------------------------------------------------------------------------


class TestComposeHooksFailClosed:
    """Verify composed hooks deny on any exception (fail-closed)."""

    @pytest.mark.asyncio
    async def test_composed_hook_denies_when_hook_raises(self):
        """If any composed hook raises, should return DENY."""
        async def _exploding_hook(tool_call: ToolCall) -> ToolDecision:
            raise RuntimeError("hook crashed")

        composed = _compose_hooks([_exploding_hook])
        decision = await composed(_make_tool_call())
        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_composed_hook_denies_when_second_hook_raises(self):
        """If the second hook raises after first allows, should DENY."""
        async def _allow_hook(tool_call: ToolCall) -> ToolDecision:
            return ToolDecision.ALLOW

        async def _exploding_hook(tool_call: ToolCall) -> ToolDecision:
            raise RuntimeError("second hook crashed")

        composed = _compose_hooks([_allow_hook, _exploding_hook])
        decision = await composed(_make_tool_call())
        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_composed_hook_first_deny_wins(self):
        """First DENY should short-circuit (normal behavior)."""
        async def _deny_hook(tool_call: ToolCall) -> ToolDecision:
            return ToolDecision.DENY

        async def _allow_hook(tool_call: ToolCall) -> ToolDecision:
            return ToolDecision.ALLOW

        composed = _compose_hooks([_deny_hook, _allow_hook])
        decision = await composed(_make_tool_call())
        assert decision == ToolDecision.DENY


# ---------------------------------------------------------------------------
# DirectToolHandler.execute() fail-closed on permission check error
# ---------------------------------------------------------------------------


class TestDirectToolHandlerPermissionFailClosed:
    """Verify execute() denies when check_permission raises (fail-closed)."""

    @pytest.mark.asyncio
    async def test_execute_denies_on_permission_check_exception(self):
        """If check_permission raises, execute() should return DENY result."""

        async def _exploding_hook(tool_call: ToolCall) -> ToolDecision:
            raise RuntimeError("permission system down")

        handler = DirectToolHandler(
            working_dir="/tmp",
            pre_hook=_exploding_hook,
        )

        tool_call = _make_tool_call("read_file")
        result = await handler.execute(tool_call)

        assert result.is_error is True
        assert "denied by permission policy" in result.content

    @pytest.mark.asyncio
    async def test_execute_allows_when_no_hook(self):
        """With no pre_hook, execute() should attempt tool execution (ALLOW)."""
        handler = DirectToolHandler(working_dir="/tmp")
        tool_call = ToolCall(
            id="test-id",
            name="read_file",
            input={"path": "/nonexistent/file.txt"},
        )
        # Should not crash from permission — it will fail in the executor
        # but that's fine, we're testing permission behavior
        result = await handler.execute(tool_call)
        # Should NOT have permission denial message
        assert "denied by permission policy" not in result.content
