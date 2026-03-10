"""Tests for Claude adapter permission system.

Verifies that the SDK-native permission mechanisms are correctly configured:
- YOLO mode → permission_mode='bypassPermissions' in SDK options
- GRANULAR mode → can_use_tool callback present, correctly maps decisions
- ASK mode → can_use_tool callback denies (no interactive user in autonomous mode)
- Per-tool allow/deny from PermissionConfig honored
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.tools.base import ToolDecision
from app.services.tools.permissions import (
    PermissionChecker,
    PermissionConfig,
    PermissionMode,
    ToolPermission,
)


class TestBuildCanUseTool:
    """Tests for _build_can_use_tool() callback mapping."""

    def _make_checker(self, config: PermissionConfig) -> PermissionChecker:
        return PermissionChecker(config)

    def _make_context(self) -> Any:
        """Create a mock ToolPermissionContext."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_allow_decision_returns_allow(self) -> None:
        """PermissionChecker ALLOW → PermissionResultAllow."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        config = PermissionConfig.yolo()
        checker = self._make_checker(config)
        callback = _build_can_use_tool(checker)

        result = await callback("Bash", {"command": "ls"}, self._make_context())
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_deny_decision_returns_deny(self) -> None:
        """PermissionChecker DENY → PermissionResultDeny with message."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        # Use lowercase: SDK "Bash" is normalized to "bash" before checker sees it.
        config = PermissionConfig.granular(deny=["bash"])
        checker = self._make_checker(config)
        callback = _build_can_use_tool(checker)

        result = await callback("Bash", {"command": "ls"}, self._make_context())
        assert result.behavior == "deny"
        assert "denied by permission policy" in result.message

    @pytest.mark.asyncio
    async def test_ask_decision_returns_deny_in_autonomous(self) -> None:
        """PermissionChecker ASK → PermissionResultDeny (no user to confirm)."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        config = PermissionConfig.ask_all()
        checker = self._make_checker(config)
        callback = _build_can_use_tool(checker)

        # SDK "Write" normalizes to "write_file" before checker
        result = await callback("Write", {"path": "foo.py"}, self._make_context())
        assert result.behavior == "deny"
        assert "requires confirmation" in result.message

    @pytest.mark.asyncio
    async def test_granular_allow_list_honored(self) -> None:
        """Tool in allow_list → ALLOW."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        # Use normalized names: "Bash" → "bash", "Read" → "read_file"
        config = PermissionConfig.granular(allow=["bash", "read_file"])
        checker = self._make_checker(config)
        callback = _build_can_use_tool(checker)

        result = await callback("Bash", {"command": "echo ok"}, self._make_context())
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_granular_deny_list_honored(self) -> None:
        """Tool in deny_list → DENY."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        config = PermissionConfig.granular(allow=["read_file"], deny=["bash"])
        checker = self._make_checker(config)
        callback = _build_can_use_tool(checker)

        result = await callback("Bash", {"command": "rm -rf /"}, self._make_context())
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_granular_unlisted_tool_asks(self) -> None:
        """Tool not in any list in granular mode → ASK → deny in autonomous."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        config = PermissionConfig.granular(allow=["read_file"])
        checker = self._make_checker(config)
        callback = _build_can_use_tool(checker)

        # SDK "Write" normalizes to "write_file", not in allow list → ASK
        result = await callback("Write", {"path": "x"}, self._make_context())
        assert result.behavior == "deny"
        assert "requires confirmation" in result.message

    @pytest.mark.asyncio
    async def test_per_tool_permission_override(self) -> None:
        """Per-tool permission takes precedence over allow/deny lists."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        config = PermissionConfig.granular(deny=["bash"])
        config.add_tool_permission(ToolPermission(name="bash", allowed=True))
        checker = self._make_checker(config)
        callback = _build_can_use_tool(checker)

        result = await callback("Bash", {"command": "ls"}, self._make_context())
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_per_tool_deny_overrides_allow_list(self) -> None:
        """Per-tool denied overrides allow list."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        config = PermissionConfig.granular(allow=["bash"])
        config.add_tool_permission(ToolPermission(name="bash", allowed=False))
        checker = self._make_checker(config)
        callback = _build_can_use_tool(checker)

        result = await callback("Bash", {"command": "ls"}, self._make_context())
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_persona_raw_git_commit_denied_without_checker(self) -> None:
        """Persona raw git publish policy applies even without other permission hooks."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        callback = _build_can_use_tool(checker=None, project_id=None, agent_slug="persona")

        result = await callback("Bash", {"command": "git commit -m 'test'"}, self._make_context())
        assert result.behavior == "deny"
        assert "workflow policy" in result.message

    @pytest.mark.asyncio
    async def test_persona_safe_bash_allowed_without_checker(self) -> None:
        """Persona still keeps normal Bash access when command is not blocked."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        callback = _build_can_use_tool(checker=None, project_id=None, agent_slug="persona")

        result = await callback("Bash", {"command": "git status --short"}, self._make_context())
        assert result.behavior == "allow"


class TestToolNameNormalization:
    """Tests for _normalize_tool_name() — MCP prefix + SDK PascalCase."""

    def test_strips_mcp_prefix(self) -> None:
        from app.adapters.claude_tools_helpers import _normalize_tool_name

        assert _normalize_tool_name("mcp__agent-hub__write_user_context") == "write_user_context"

    def test_preserves_bare_name(self) -> None:
        from app.adapters.claude_tools_helpers import _normalize_tool_name

        assert _normalize_tool_name("write_user_context") == "write_user_context"

    def test_maps_bash_to_lowercase(self) -> None:
        from app.adapters.claude_tools_helpers import _normalize_tool_name

        assert _normalize_tool_name("Bash") == "bash"

    def test_maps_read_to_read_file(self) -> None:
        from app.adapters.claude_tools_helpers import _normalize_tool_name

        assert _normalize_tool_name("Read") == "read_file"

    def test_maps_write_to_write_file(self) -> None:
        from app.adapters.claude_tools_helpers import _normalize_tool_name

        assert _normalize_tool_name("Write") == "write_file"

    def test_maps_edit_to_write_file(self) -> None:
        from app.adapters.claude_tools_helpers import _normalize_tool_name

        assert _normalize_tool_name("Edit") == "write_file"

    def test_handles_single_underscore_prefix(self) -> None:
        from app.adapters.claude_tools_helpers import _normalize_tool_name

        assert _normalize_tool_name("mcp_notreal") == "mcp_notreal"


class TestBuildCanUseToolComposition:
    """Tests for 3-layer hook composition in _build_can_use_tool."""

    def _make_context(self) -> Any:
        return MagicMock()

    @pytest.mark.asyncio
    async def test_no_hooks_returns_allow(self) -> None:
        """No checker, no project_id → always allow."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        callback = _build_can_use_tool(checker=None, project_id=None)
        result = await callback("Bash", {"command": "ls"}, self._make_context())
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_checker_only_composes(self) -> None:
        """Checker without project_id → only PermissionChecker hook."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        # Deny list uses lowercase because _build_can_use_tool normalizes
        # SDK PascalCase ("Bash" → "bash") before passing to the checker.
        config = PermissionConfig.granular(deny=["bash"])
        checker = PermissionChecker(config)
        callback = _build_can_use_tool(checker=checker, project_id=None)

        result = await callback("Bash", {"command": "ls"}, self._make_context())
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_mcp_prefix_normalized_before_checker(self) -> None:
        """MCP-prefixed name is stripped before passing to PermissionChecker."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        config = PermissionConfig.granular(allow=["write_user_context"])
        checker = PermissionChecker(config)
        callback = _build_can_use_tool(checker=checker, project_id=None)

        result = await callback(
            "mcp__agent-hub__write_user_context",
            {"user_context": "test"},
            self._make_context(),
        )
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_mcp_prefix_denied_without_normalization_would_fail(self) -> None:
        """Verify that the prefixed name alone would be denied (sanity check)."""

        config = PermissionConfig.granular(allow=["write_user_context"])
        checker = PermissionChecker(config)

        # Directly test that the raw MCP name isn't in the allow list
        from app.services.tools.base import ToolCall

        decision = await checker.check(
            ToolCall(id="", name="mcp__agent-hub__write_user_context", input={})
        )
        assert decision != ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_project_id_only_builds_callback(self) -> None:
        """project_id without checker still builds a callback (for project hooks)."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        callback = _build_can_use_tool(checker=None, project_id="test-project")
        assert callable(callback)

    @pytest.mark.asyncio
    async def test_project_hooks_with_checker(self) -> None:
        """Both project_id and checker compose all 3 layers."""
        from app.adapters.claude_tools_helpers import _build_can_use_tool

        config = PermissionConfig.granular(allow=["write_user_context", "read_user_context"])
        checker = PermissionChecker(config)
        callback = _build_can_use_tool(checker=checker, project_id="test-project")
        assert callable(callback)


class TestSDKOptionsYoloMode:
    """YOLO mode should set permission_mode='bypassPermissions' in SDK options."""

    @pytest.mark.asyncio
    async def test_yolo_without_working_dir_sets_bypass_permissions(self) -> None:
        """Yolo mode without working_dir passes permission_mode='bypassPermissions'."""
        from app.adapters.base import Message

        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        async def mock_query(**kwargs: Any):
            return
            yield  # type: ignore[misc]

        with (
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options),
            patch("claude_agent_sdk.query", side_effect=mock_query),
        ):
            from app.adapters.claude_tools_helpers import complete_with_tools

            gen = complete_with_tools(
                messages=[Message(role="user", content="test")],
                model="sonnet",
                tools=[],
                yolo_mode=True,
                permission_checker=None,
                working_dir=None,
                resume_session_id=None,
                cli_path="/usr/bin/claude",
                model_map={"sonnet": "sonnet"},
                provider_name="claude",
                after_tool_callback=None,
            )
            try:
                async for _ in gen:
                    pass
            except Exception:
                pass

        assert captured_opts.get("permission_mode") == "bypassPermissions"
        assert "can_use_tool" not in captured_opts

    @pytest.mark.asyncio
    async def test_persona_yolo_without_working_dir_sets_can_use_tool(self) -> None:
        """Persona without working_dir still installs a permission callback for raw git policy."""
        from app.adapters.base import Message

        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        async def mock_query(**kwargs: Any):
            return
            yield  # type: ignore[misc]

        with (
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options),
            patch("claude_agent_sdk.query", side_effect=mock_query),
        ):
            from app.adapters.claude_tools_helpers import complete_with_tools

            gen = complete_with_tools(
                messages=[Message(role="user", content="test")],
                model="sonnet",
                tools=[],
                yolo_mode=True,
                permission_checker=None,
                working_dir=None,
                resume_session_id=None,
                cli_path="/usr/bin/claude",
                model_map={"sonnet": "sonnet"},
                provider_name="claude",
                after_tool_callback=None,
                agent_slug="persona",
            )
            try:
                async for _ in gen:
                    pass
            except Exception:
                pass

        assert captured_opts.get("permission_mode") == "default"
        assert callable(captured_opts.get("can_use_tool"))

    @pytest.mark.asyncio
    async def test_yolo_with_working_dir_uses_settings_enforcement(self) -> None:
        """Yolo mode with working_dir uses settings-based boundary enforcement."""
        from app.adapters.base import Message

        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        async def mock_query(**kwargs: Any):
            return
            yield  # type: ignore[misc]

        with (
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options),
            patch("claude_agent_sdk.query", side_effect=mock_query),
        ):
            from app.adapters.claude_tools_helpers import complete_with_tools

            gen = complete_with_tools(
                messages=[Message(role="user", content="test")],
                model="sonnet",
                tools=[],
                yolo_mode=True,
                permission_checker=None,
                working_dir="/tmp/test-worktree",
                resume_session_id=None,
                cli_path="/usr/bin/claude",
                model_map={"sonnet": "sonnet"},
                provider_name="claude",
                after_tool_callback=None,
            )
            try:
                async for _ in gen:
                    pass
            except Exception:
                pass

        assert captured_opts.get("permission_mode") == "acceptEdits"
        assert "settings" in captured_opts
        assert "hooks" in captured_opts

    @pytest.mark.asyncio
    async def test_granular_without_working_dir_sets_can_use_tool(self) -> None:
        """Non-yolo with permission_checker but no working_dir passes can_use_tool callback."""
        from app.adapters.base import Message

        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        async def mock_query(**kwargs: Any):
            return
            yield  # type: ignore[misc]

        config = PermissionConfig.granular(allow=["Bash", "Read"])
        checker = PermissionChecker(config)

        with (
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options),
            patch("claude_agent_sdk.query", side_effect=mock_query),
        ):
            from app.adapters.claude_tools_helpers import complete_with_tools

            gen = complete_with_tools(
                messages=[Message(role="user", content="test")],
                model="sonnet",
                tools=[],
                yolo_mode=False,
                permission_checker=checker,
                working_dir=None,
                resume_session_id=None,
                cli_path="/usr/bin/claude",
                model_map={"sonnet": "sonnet"},
                provider_name="claude",
                after_tool_callback=None,
            )
            try:
                async for _ in gen:
                    pass
            except Exception:
                pass

        assert captured_opts.get("permission_mode") == "default"
        assert callable(captured_opts.get("can_use_tool"))

    @pytest.mark.asyncio
    async def test_granular_with_working_dir_uses_both(self) -> None:
        """Non-yolo with working_dir uses settings enforcement + can_use_tool fallback."""
        from app.adapters.base import Message

        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        async def mock_query(**kwargs: Any):
            return
            yield  # type: ignore[misc]

        config = PermissionConfig.granular(allow=["Bash", "Read"])
        checker = PermissionChecker(config)

        with (
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options),
            patch("claude_agent_sdk.query", side_effect=mock_query),
        ):
            from app.adapters.claude_tools_helpers import complete_with_tools

            gen = complete_with_tools(
                messages=[Message(role="user", content="test")],
                model="sonnet",
                tools=[],
                yolo_mode=False,
                permission_checker=checker,
                working_dir="/tmp/test-worktree",
                resume_session_id=None,
                cli_path="/usr/bin/claude",
                model_map={"sonnet": "sonnet"},
                provider_name="claude",
                after_tool_callback=None,
            )
            try:
                async for _ in gen:
                    pass
            except Exception:
                pass

        # Settings-based enforcement is primary
        assert captured_opts.get("permission_mode") == "acceptEdits"
        assert "settings" in captured_opts
        assert "hooks" in captured_opts
        # can_use_tool kept as fallback for non-builtin tools
        assert callable(captured_opts.get("can_use_tool"))


class TestAdapterPermissionConfig:
    """ClaudeAdapter.complete_with_tools() correctly parses permission_config."""

    @pytest.mark.asyncio
    async def test_none_config_is_yolo(self) -> None:
        """None permission_config defaults to yolo mode (same logic as ClaudeAdapter)."""
        config = None
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

        from app.services.tools.base import ToolCall

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
        from app.services.tools.base import ToolCall

        decision = await checker.check(ToolCall(id="", name="Bash", input={}))
        assert decision == ToolDecision.ASK


class TestPromptWrapping:
    """Tests for _wrap_prompt_as_stream() used when can_use_tool requires streaming."""

    @pytest.mark.asyncio
    async def test_wrap_produces_async_iterable(self) -> None:
        """Wrapped prompt yields a single user message dict."""
        from app.adapters.claude_tools_helpers import _wrap_prompt_as_stream

        stream = await _wrap_prompt_as_stream("Hello world")

        messages = []
        async for msg in stream:
            messages.append(msg)

        assert len(messages) == 1
        assert messages[0]["type"] == "user"
        assert messages[0]["message"]["role"] == "user"
        assert messages[0]["message"]["content"] == "Hello world"
