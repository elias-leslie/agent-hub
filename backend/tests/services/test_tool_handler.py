"""Tests for tool_handler: fail-closed hook behavior and where the tool permission comes from."""

from __future__ import annotations

import pytest

from app.services.tools.base import ToolCall, ToolDecision
from app.services.tools.tool_handler import (
    DirectToolHandler,
    _compose_hooks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call(name: str = "read_file") -> ToolCall:
    """Create a minimal ToolCall for testing."""
    return ToolCall(id="test-id", name=name, input={})


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

    @pytest.mark.asyncio
    async def test_execute_prepends_hook_notes_to_output(self):
        """A pre-hook's notes (e.g. a lease warning) reach the model ahead of the output."""

        async def _warning_hook(tool_call: ToolCall) -> ToolDecision:
            tool_call.notes.append("WARNING: file.txt leased by cc:abc123")
            return ToolDecision.ALLOW

        handler = DirectToolHandler(working_dir="/tmp", pre_hook=_warning_hook)
        result = await handler.execute(
            ToolCall(id="test-id", name="read_file", input={"path": "/nonexistent/file.txt"})
        )

        assert result.content.startswith("WARNING: file.txt leased by cc:abc123\n")


# ---------------------------------------------------------------------------
# Who decides which calls run: only a workflow run's tool set (chat has no tool hook)
# ---------------------------------------------------------------------------


class TestToolPermissionSource:
    def test_chat_has_no_tool_hook(self):
        """Without a permitted tool set (Agent Hub chat) the model's tools come from its agent registry;
        only the lease check applies."""
        from app.services.tools.tool_handler import _collect_hooks

        assert len(_collect_hooks(None, "chat-project")) == 1  # lease check

    def test_chat_tool_surface_comes_from_the_agent_registry(self):
        from app.api.complete.tool_provisioner import provision_standard_tools
        from app.services.tools.tool_definitions import get_agent_tool_specs

        provisioned = provision_standard_tools(True, None, agent_slug="vantage-research")
        expected = {t.name for t in get_agent_tool_specs("vantage-research") or []}
        assert {t["name"] for t in provisioned.loaded_tools} == expected
        assert "bash" not in expected

    @pytest.mark.asyncio
    async def test_a_permitted_tool_set_allows_only_its_tools(self):
        """A workflow run names its tools: anything outside the set is denied."""
        from app.services.tools.tool_handler import _collect_hooks

        hooks = _collect_hooks(None, "chat-project", frozenset({"bash", "edit_file"}))
        assert len(hooks) == 2  # tool set, lease check
        assert await hooks[0](_make_tool_call("bash")) == ToolDecision.ALLOW
        assert await hooks[0](_make_tool_call("write_file")) == ToolDecision.DENY
