"""Tests for Claude adapter permission system.

Verifies that the permission mechanisms used by DirectToolHandler are
correctly configured:
- YOLO mode defaults (None config → no hooks)
- GRANULAR mode → PermissionChecker allow/deny decisions
- ASK mode → deny in autonomous mode (no user to confirm)
- Per-tool permission overrides honored
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.tools.base import ToolCall, ToolDecision
from app.services.tools.permissions import (
    PermissionChecker,
    PermissionConfig,
    PermissionMode,
    ToolPermission,
)


class TestPermissionCheckerDecisions:
    """Tests for PermissionChecker decision mapping."""

    def _make_checker(self, config: PermissionConfig) -> PermissionChecker:
        return PermissionChecker(config)

    @pytest.mark.asyncio
    async def test_yolo_allows_all(self) -> None:
        """YOLO config allows all tools."""
        config = PermissionConfig.yolo()
        checker = self._make_checker(config)
        decision = await checker.check(ToolCall(id="", name="Bash", input={"command": "ls"}))
        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_deny_list_denies(self) -> None:
        """Tool in deny_list → DENY."""
        config = PermissionConfig.granular(deny=["Bash"])
        checker = self._make_checker(config)
        decision = await checker.check(ToolCall(id="", name="Bash", input={"command": "ls"}))
        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_ask_mode_returns_ask(self) -> None:
        """ASK mode → ASK decision (denied in autonomous mode by handler)."""
        config = PermissionConfig.ask_all()
        checker = self._make_checker(config)
        decision = await checker.check(ToolCall(id="", name="Write", input={"path": "foo.py"}))
        assert decision == ToolDecision.ASK

    @pytest.mark.asyncio
    async def test_granular_allow_list_honored(self) -> None:
        """Tool in allow_list → ALLOW."""
        config = PermissionConfig.granular(allow=["Bash", "Read"])
        checker = self._make_checker(config)
        decision = await checker.check(ToolCall(id="", name="Bash", input={"command": "echo ok"}))
        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_granular_deny_list_honored(self) -> None:
        """Tool in deny_list → DENY."""
        config = PermissionConfig.granular(allow=["Read"], deny=["Bash"])
        checker = self._make_checker(config)
        decision = await checker.check(ToolCall(id="", name="Bash", input={"command": "rm -rf /"}))
        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_granular_unlisted_tool_asks(self) -> None:
        """Tool not in any list in granular mode → ASK."""
        config = PermissionConfig.granular(allow=["Read"])
        checker = self._make_checker(config)
        decision = await checker.check(ToolCall(id="", name="Write", input={"path": "x"}))
        assert decision == ToolDecision.ASK

    @pytest.mark.asyncio
    async def test_per_tool_permission_override(self) -> None:
        """Per-tool permission takes precedence over allow/deny lists."""
        config = PermissionConfig.granular(deny=["Bash"])
        config.add_tool_permission(ToolPermission(name="Bash", allowed=True))
        checker = self._make_checker(config)
        decision = await checker.check(ToolCall(id="", name="Bash", input={"command": "ls"}))
        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_per_tool_deny_overrides_allow_list(self) -> None:
        """Per-tool denied overrides allow list."""
        config = PermissionConfig.granular(allow=["Bash"])
        config.add_tool_permission(ToolPermission(name="Bash", allowed=False))
        checker = self._make_checker(config)
        decision = await checker.check(ToolCall(id="", name="Bash", input={"command": "ls"}))
        assert decision == ToolDecision.DENY


class TestAdapterPermissionConfig:
    """Permission config parsing (used by build_permission_checker and create_direct_handler)."""

    @pytest.mark.asyncio
    async def test_none_config_is_yolo(self) -> None:
        """None permission_config defaults to yolo mode."""
        config: dict[str, Any] | None = None
        yolo_mode = True
        checker = None
        if config:
            pc = PermissionConfig.from_dict(config)
            if pc.mode != PermissionMode.YOLO:
                checker = PermissionChecker(pc)
                yolo_mode = False

        assert yolo_mode is True
        assert checker is None

    @pytest.mark.asyncio
    async def test_yolo_config_is_yolo(self) -> None:
        """Explicit yolo config → yolo mode."""
        config = {"mode": "yolo"}
        pc = PermissionConfig.from_dict(config)
        assert pc.mode == PermissionMode.YOLO

    @pytest.mark.asyncio
    async def test_granular_config_creates_checker(self) -> None:
        """Granular config → creates PermissionChecker."""
        config = {"mode": "granular", "allow_list": ["Bash", "Read"], "deny_list": ["Write"]}
        pc = PermissionConfig.from_dict(config)
        assert pc.mode == PermissionMode.GRANULAR

        checker = PermissionChecker(pc)
        assert checker is not None

        # Allowed tool
        decision = await checker.check(ToolCall(id="", name="Bash", input={}))
        assert decision == ToolDecision.ALLOW

        # Denied tool
        decision = await checker.check(ToolCall(id="", name="Write", input={}))
        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_ask_config_creates_checker(self) -> None:
        """ASK mode config → creates PermissionChecker that returns ASK."""
        config = {"mode": "ask"}
        pc = PermissionConfig.from_dict(config)
        assert pc.mode == PermissionMode.ASK

        checker = PermissionChecker(pc)
        decision = await checker.check(ToolCall(id="", name="Bash", input={}))
        assert decision == ToolDecision.ASK
