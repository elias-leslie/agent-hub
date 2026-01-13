"""Tests for tool permission model."""

import pytest

from app.services.tools.base import ToolCall, ToolDecision
from app.services.tools.permissions import (
    PermissionChecker,
    PermissionConfig,
    PermissionMode,
    ToolPermission,
)


class TestToolPermission:
    """Tests for ToolPermission."""

    def test_allowed_tool(self):
        """Test allowed tool returns ALLOW."""
        perm = ToolPermission(name="test", allowed=True, requires_confirmation=False)
        assert perm.get_decision() == ToolDecision.ALLOW

    def test_denied_tool(self):
        """Test denied tool returns DENY."""
        perm = ToolPermission(name="test", allowed=False)
        assert perm.get_decision() == ToolDecision.DENY

    def test_requires_confirmation(self):
        """Test tool requiring confirmation returns ASK."""
        perm = ToolPermission(name="test", allowed=True, requires_confirmation=True)
        assert perm.get_decision() == ToolDecision.ASK

    def test_denied_overrides_confirmation(self):
        """Test denied takes precedence over confirmation."""
        perm = ToolPermission(name="test", allowed=False, requires_confirmation=True)
        assert perm.get_decision() == ToolDecision.DENY


class TestPermissionConfigYolo:
    """Tests for YOLO mode."""

    def test_yolo_allows_all(self):
        """Test YOLO mode auto-approves all tools."""
        config = PermissionConfig.yolo()

        calls = [
            ToolCall(id="1", name="read_file", input={}),
            ToolCall(id="2", name="write_file", input={}),
            ToolCall(id="3", name="execute_code", input={}),
        ]

        for call in calls:
            assert config.get_decision(call) == ToolDecision.ALLOW

    def test_yolo_respects_deny_list(self):
        """Test YOLO mode still respects deny list."""
        config = PermissionConfig.yolo()
        config.deny_tool("dangerous_tool")

        assert (
            config.get_decision(ToolCall(id="1", name="safe_tool", input={})) == ToolDecision.ALLOW
        )
        assert (
            config.get_decision(ToolCall(id="2", name="dangerous_tool", input={}))
            == ToolDecision.DENY
        )

    def test_yolo_respects_tool_permissions(self):
        """Test YOLO mode respects per-tool permissions."""
        config = PermissionConfig.yolo()
        config.add_tool_permission(ToolPermission(name="special", requires_confirmation=True))

        assert config.get_decision(ToolCall(id="1", name="normal", input={})) == ToolDecision.ALLOW
        assert config.get_decision(ToolCall(id="2", name="special", input={})) == ToolDecision.ASK


class TestPermissionConfigAsk:
    """Tests for ASK mode."""

    def test_ask_requires_confirmation_for_all(self):
        """Test ASK mode requires confirmation for all tools."""
        config = PermissionConfig.ask_all()

        calls = [
            ToolCall(id="1", name="read_file", input={}),
            ToolCall(id="2", name="write_file", input={}),
        ]

        for call in calls:
            assert config.get_decision(call) == ToolDecision.ASK

    def test_ask_respects_deny_list(self):
        """Test ASK mode still denies blocked tools."""
        config = PermissionConfig.ask_all()
        config.deny_tool("blocked")

        assert config.get_decision(ToolCall(id="1", name="blocked", input={})) == ToolDecision.DENY

    def test_ask_respects_tool_permissions(self):
        """Test ASK mode respects per-tool auto-allow."""
        config = PermissionConfig.ask_all()
        config.add_tool_permission(
            ToolPermission(name="auto_allowed", allowed=True, requires_confirmation=False)
        )

        assert (
            config.get_decision(ToolCall(id="1", name="auto_allowed", input={}))
            == ToolDecision.ALLOW
        )
        assert config.get_decision(ToolCall(id="2", name="other", input={})) == ToolDecision.ASK


class TestPermissionConfigGranular:
    """Tests for GRANULAR mode."""

    def test_granular_allows_whitelist(self):
        """Test granular mode allows tools on allow list."""
        config = PermissionConfig.granular(allow=["read_file", "list_files"])

        assert (
            config.get_decision(ToolCall(id="1", name="read_file", input={})) == ToolDecision.ALLOW
        )
        assert (
            config.get_decision(ToolCall(id="2", name="list_files", input={})) == ToolDecision.ALLOW
        )

    def test_granular_asks_for_unknown(self):
        """Test granular mode asks for unknown tools."""
        config = PermissionConfig.granular(allow=["read_file"])

        assert (
            config.get_decision(ToolCall(id="1", name="unknown_tool", input={})) == ToolDecision.ASK
        )

    def test_granular_denies_blacklist(self):
        """Test granular mode denies tools on deny list."""
        config = PermissionConfig.granular(deny=["execute_code"])

        assert (
            config.get_decision(ToolCall(id="1", name="execute_code", input={}))
            == ToolDecision.DENY
        )

    def test_granular_deny_overrides_allow(self):
        """Test deny list takes precedence in granular mode."""
        config = PermissionConfig.granular(allow=["tool1"], deny=["tool1"])

        # Deny list checked before allow list
        assert config.get_decision(ToolCall(id="1", name="tool1", input={})) == ToolDecision.DENY

    def test_granular_tool_permission_overrides_lists(self):
        """Test per-tool permissions override allow/deny lists."""
        config = PermissionConfig.granular(deny=["special_tool"])
        config.add_tool_permission(ToolPermission(name="special_tool", allowed=True))

        # Per-tool permission takes precedence
        assert (
            config.get_decision(ToolCall(id="1", name="special_tool", input={}))
            == ToolDecision.ALLOW
        )


class TestPermissionConfigSerialization:
    """Tests for config serialization."""

    def test_to_dict(self):
        """Test config serializes to dict."""
        config = PermissionConfig.granular(allow=["tool1"], deny=["tool2"])
        config.add_tool_permission(ToolPermission(name="special", requires_confirmation=True))

        data = config.to_dict()

        assert data["mode"] == "granular"
        assert "tool1" in data["allow_list"]
        assert "tool2" in data["deny_list"]
        assert "special" in data["tool_permissions"]
        assert data["tool_permissions"]["special"]["requires_confirmation"] is True

    def test_from_dict(self):
        """Test config deserializes from dict."""
        data = {
            "mode": "granular",
            "allow_list": ["tool1", "tool2"],
            "deny_list": ["blocked"],
            "tool_permissions": {
                "special": {
                    "name": "special",
                    "allowed": True,
                    "requires_confirmation": True,
                }
            },
        }

        config = PermissionConfig.from_dict(data)

        assert config.mode == PermissionMode.GRANULAR
        assert "tool1" in config.allow_list
        assert "blocked" in config.deny_list
        assert "special" in config.tool_permissions

    def test_roundtrip(self):
        """Test serialize/deserialize roundtrip."""
        original = PermissionConfig.granular(allow=["a", "b"], deny=["c"])
        original.add_tool_permission(ToolPermission(name="x", requires_confirmation=True))

        restored = PermissionConfig.from_dict(original.to_dict())

        # Verify same behavior
        call = ToolCall(id="1", name="a", input={})
        assert original.get_decision(call) == restored.get_decision(call)

        call = ToolCall(id="2", name="c", input={})
        assert original.get_decision(call) == restored.get_decision(call)

        call = ToolCall(id="3", name="x", input={})
        assert original.get_decision(call) == restored.get_decision(call)


class TestPermissionConfigHelpers:
    """Tests for config helper methods."""

    def test_allow_tool(self):
        """Test adding tool to allow list."""
        config = PermissionConfig.granular()
        config.allow_tool("new_tool")

        assert "new_tool" in config.allow_list

    def test_deny_tool(self):
        """Test adding tool to deny list."""
        config = PermissionConfig.granular()
        config.deny_tool("bad_tool")

        assert "bad_tool" in config.deny_list

    def test_allow_removes_from_deny(self):
        """Test allow removes from deny list."""
        config = PermissionConfig.granular(deny=["tool"])
        config.allow_tool("tool")

        assert "tool" in config.allow_list
        assert "tool" not in config.deny_list

    def test_deny_removes_from_allow(self):
        """Test deny removes from allow list."""
        config = PermissionConfig.granular(allow=["tool"])
        config.deny_tool("tool")

        assert "tool" not in config.allow_list
        assert "tool" in config.deny_list


class TestPermissionChecker:
    """Tests for PermissionChecker."""

    @pytest.mark.asyncio
    async def test_check_with_yolo(self):
        """Test checker with YOLO config."""
        checker = PermissionChecker(PermissionConfig.yolo())
        call = ToolCall(id="1", name="anything", input={})

        decision = await checker.check(call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_check_with_granular(self):
        """Test checker with granular config."""
        checker = PermissionChecker(PermissionConfig.granular(allow=["allowed"]))

        assert await checker.check(ToolCall(id="1", name="allowed", input={})) == ToolDecision.ALLOW
        assert await checker.check(ToolCall(id="2", name="unknown", input={})) == ToolDecision.ASK

    def test_update_config(self):
        """Test updating checker config."""
        checker = PermissionChecker(PermissionConfig.yolo())
        assert checker.config.mode == PermissionMode.YOLO

        checker.update_config(PermissionConfig.ask_all())
        assert checker.config.mode == PermissionMode.ASK

    @pytest.mark.asyncio
    async def test_create_hook(self):
        """Test creating hook callback."""
        checker = PermissionChecker(PermissionConfig.yolo())
        hook = checker.create_hook()

        call = ToolCall(id="1", name="test", input={})
        decision = await hook(call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_hook_respects_config_updates(self):
        """Test hook reflects config changes."""
        checker = PermissionChecker(PermissionConfig.yolo())
        hook = checker.create_hook()

        call = ToolCall(id="1", name="test", input={})

        # Initially YOLO
        assert await hook(call) == ToolDecision.ALLOW

        # Update to ASK
        checker.update_config(PermissionConfig.ask_all())
        assert await hook(call) == ToolDecision.ASK
