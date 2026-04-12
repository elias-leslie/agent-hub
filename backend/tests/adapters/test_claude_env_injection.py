"""Tests for Claude adapter environment injection.

Verifies that all three Claude adapter paths (tools, oauth, streaming)
pass build_venv_env_overlay() result to ClaudeAgentOptions.env, ensuring
agents in worktrees get the correct VIRTUAL_ENV and PATH.

This is the integration test that verifies the fix for:
  "Agent's Bash tool in worktrees doesn't have VIRTUAL_ENV"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import Message
from app.constants.models import CLAUDE_SONNET


def _make_venv(tmp_path: Path) -> Path:
    """Create a fake venv with python binary."""
    venv = tmp_path / "backend" / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/usr/bin/env python3\n")
    return tmp_path / "backend" / ".venv"


def _make_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a fake worktree pointing to a main repo with venv.

    Returns (worktree_path, expected_venv_path).
    """
    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    (main_repo / ".git").mkdir()
    (main_repo / ".git" / "worktrees" / "task-abc").mkdir(parents=True)
    venv = main_repo / "backend" / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/usr/bin/env python3\n")

    worktree = tmp_path / "worktree-abc"
    worktree.mkdir()
    gitdir = str(main_repo / ".git" / "worktrees" / "task-abc")
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n")

    return worktree, main_repo / "backend" / ".venv"


class TestClaudeToolsEnvInjection:
    """Tests for env injection in claude_tools.complete_with_tools()."""

    async def _run_complete_with_tools(self, working_dir: str, captured_opts: dict[str, Any]) -> None:
        """Helper to invoke complete_with_tools and capture ClaudeAgentOptions kwargs."""

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        async def mock_query(**kwargs: Any):
            return
            yield None

        with (
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options),
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.HookMatcher"),
        ):
            from app.adapters.claude_tools_helpers import complete_with_tools

            gen = complete_with_tools(
                messages=[Message(role="user", content="test")],
                model=CLAUDE_SONNET,
                tools=[],
                yolo_mode=True,
                permission_checker=None,
                working_dir=working_dir,
                resume_session_id=None,
                cli_path="/usr/bin/claude",
                model_map={},
                provider_name="claude",
                after_tool_callback=None,
            )
            try:
                async for _ in gen:
                    pass
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_env_passed_to_sdk_options_main_repo(self, tmp_path: Path) -> None:
        """ClaudeAgentOptions receives env with VIRTUAL_ENV for main repo."""
        venv_path = _make_venv(tmp_path)
        captured_opts: dict[str, Any] = {}
        await self._run_complete_with_tools(str(tmp_path), captured_opts)

        assert "env" in captured_opts
        assert captured_opts["env"]["VIRTUAL_ENV"] == str(venv_path)
        assert str(venv_path / "bin") in captured_opts["env"]["PATH"]

    @pytest.mark.asyncio
    async def test_env_passed_to_sdk_options_worktree(self, tmp_path: Path) -> None:
        """ClaudeAgentOptions receives env with main repo's VIRTUAL_ENV for worktree."""
        worktree, expected_venv = _make_worktree(tmp_path)
        captured_opts: dict[str, Any] = {}
        await self._run_complete_with_tools(str(worktree), captured_opts)

        assert "env" in captured_opts
        assert captured_opts["env"]["VIRTUAL_ENV"] == str(expected_venv)
        assert "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT" not in captured_opts["env"]

    @pytest.mark.asyncio
    async def test_env_empty_when_no_venv(self, tmp_path: Path) -> None:
        """No venv found keeps env minimal apart from shared command-guard vars."""
        captured_opts: dict[str, Any] = {}
        await self._run_complete_with_tools(str(tmp_path), captured_opts)

        assert "env" in captured_opts
        assert "VIRTUAL_ENV" not in captured_opts["env"]
        assert "PYTHONHOME" not in captured_opts["env"]

    @pytest.mark.asyncio
    async def test_pythonhome_overridden(self, tmp_path: Path) -> None:
        """PYTHONHOME is set to empty string in overlay to neutralize it."""
        _make_venv(tmp_path)
        captured_opts: dict[str, Any] = {}
        await self._run_complete_with_tools(str(tmp_path), captured_opts)

        assert captured_opts["env"]["PYTHONHOME"] == ""


class TestClaudeOAuthEnvInjection:
    """Tests for env injection via build_sdk_options (oauth path)."""

    @staticmethod
    def _build_and_capture(tmp_path: Path, **extra_kwargs: Any) -> dict[str, Any]:
        """Call build_sdk_options and return the captured ClaudeAgentOptions kwargs."""
        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        with patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options):
            from app.adapters.claude_utils import build_sdk_options

            build_sdk_options(
                cli_path="/usr/bin/claude",
                model="sonnet",
                model_map={"sonnet": "sonnet"},
                working_dir=str(tmp_path),
                **extra_kwargs,
            )

        return captured_opts

    def test_env_in_sdk_options_main_repo(self, tmp_path: Path) -> None:
        """build_sdk_options includes env with VIRTUAL_ENV for main repo."""
        venv_path = _make_venv(tmp_path)
        captured_opts = self._build_and_capture(tmp_path)

        assert "env" in captured_opts
        assert captured_opts["env"]["VIRTUAL_ENV"] == str(venv_path)
        assert "BASH_ENV" in captured_opts["env"]
        assert "SF_COMMAND_GUARD_BIN" in captured_opts["env"]

    def test_env_in_sdk_options_worktree(self, tmp_path: Path) -> None:
        """build_sdk_options resolves main repo venv for worktree."""
        worktree, expected_venv = _make_worktree(tmp_path)
        captured_opts = self._build_and_capture(worktree)

        assert captured_opts["env"]["VIRTUAL_ENV"] == str(expected_venv)

    def test_static_sdk_defaults(self, tmp_path: Path) -> None:
        """build_sdk_options sets file checkpointing and buffer size; no budget cap."""
        captured_opts = self._build_and_capture(tmp_path)

        assert captured_opts["enable_file_checkpointing"] is True
        assert captured_opts["max_buffer_size"] == 10 * 1024 * 1024
        assert "max_budget_usd" not in captured_opts

    def test_max_turns_forwarded(self, tmp_path: Path) -> None:
        """max_turns is passed through to ClaudeAgentOptions."""
        captured_opts = self._build_and_capture(tmp_path, max_turns=10)

        assert captured_opts["max_turns"] == 10

    def test_session_id_injected_into_sdk_env(self, tmp_path: Path) -> None:
        """Agent Hub session id should reach the Claude subprocess env."""
        captured_opts = self._build_and_capture(tmp_path, session_id="sess-123")

        assert captured_opts["env"]["AGENT_HUB_SESSION_ID"] == "sess-123"

    def test_json_mode_preserves_higher_max_turns(self, tmp_path: Path) -> None:
        """json_mode requires at least 2 turns but preserves a higher caller budget."""
        captured_opts = self._build_and_capture(
            tmp_path,
            max_turns=10,
            json_mode=True,
            json_schema={"type": "object", "properties": {"name": {"type": "string"}}},
        )

        assert captured_opts["max_turns"] == 10

    def test_json_mode_raises_low_max_turns_to_minimum(self, tmp_path: Path) -> None:
        """json_mode raises a low max_turns budget to the minimum viable value."""
        captured_opts = self._build_and_capture(
            tmp_path,
            max_turns=1,
            json_mode=True,
            json_schema={"type": "object", "properties": {"name": {"type": "string"}}},
        )

        assert captured_opts["max_turns"] == 2

    def test_allowed_tools_default(self, tmp_path: Path) -> None:
        """Default allowed_tools matches the expected CLI-builtin list."""
        captured_opts = self._build_and_capture(tmp_path)

        assert captured_opts["allowed_tools"] == ["Read", "Write", "Bash", "Edit"]

    def test_allowed_tools_custom(self, tmp_path: Path) -> None:
        """Custom allowed_tools list is forwarded as-is."""
        custom = ["Read", "Bash"]
        captured_opts = self._build_and_capture(tmp_path, allowed_tools=custom)

        assert captured_opts["allowed_tools"] == custom

    def test_disallowed_tools_default(self, tmp_path: Path) -> None:
        """Default disallowed_tools blocks Claude-native web/research builtins."""
        captured_opts = self._build_and_capture(tmp_path)

        assert captured_opts["disallowed_tools"] == [
            "WebFetch",
            "WebSearch",
            "Agent",
        ]

    def test_disallowed_tools_custom(self, tmp_path: Path) -> None:
        """Custom disallowed_tools list is forwarded as-is."""
        custom = ["WebFetch"]
        captured_opts = self._build_and_capture(tmp_path, disallowed_tools=custom)

        assert captured_opts["disallowed_tools"] == custom

    def test_system_prompt_set(self, tmp_path: Path) -> None:
        """system_prompt is included in options when provided."""
        captured_opts = self._build_and_capture(tmp_path, system_prompt="You are helpful")

        assert captured_opts["system_prompt"] == "You are helpful"

    def test_system_prompt_none(self, tmp_path: Path) -> None:
        """system_prompt key is absent when not provided."""
        captured_opts = self._build_and_capture(tmp_path)

        assert "system_prompt" not in captured_opts

    def test_mcp_servers_do_not_set_stream_close_timeout(self, tmp_path: Path) -> None:
        """MCP sessions should not inject a hardcoded stream-close timeout."""
        mock_mcp = MagicMock()
        captured_opts = self._build_and_capture(tmp_path, mcp_servers={"test": mock_mcp})

        assert "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT" not in captured_opts["env"]

    def test_working_dir_hook_mode_does_not_set_stream_close_timeout(self, tmp_path: Path) -> None:
        """working_dir hook mode stays on plain prompts and skips stream-close overrides."""
        captured_opts = self._build_and_capture(tmp_path)

        assert "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT" not in captured_opts["env"]

    def test_mcp_servers_do_not_set_os_environ_stream_close_timeout(self, tmp_path: Path) -> None:
        """MCP sessions should not mutate process env with a hardcoded stream timeout."""
        import os

        # Clear to ensure our code sets it
        os.environ.pop("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", None)
        mock_mcp = MagicMock()
        self._build_and_capture(tmp_path, mcp_servers={"test": mock_mcp})

        assert os.environ.get("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT") is None

    def test_mcp_servers_do_not_set_tool_timeout(self, tmp_path: Path) -> None:
        """MCP sessions should not inject a hardcoded tool timeout."""
        mock_mcp = MagicMock()
        captured_opts = self._build_and_capture(tmp_path, mcp_servers={"test": mock_mcp})

        assert "MCP_TOOL_TIMEOUT" not in captured_opts["env"]

    def test_working_dir_non_mcp_sessions_skip_stream_timeout(self, tmp_path: Path) -> None:
        """working_dir hook mode no longer opts into stream-input close timeout."""
        captured_opts = self._build_and_capture(tmp_path)

        assert "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT" not in captured_opts["env"]

    def test_mcp_env_preserves_venv_without_timeout_overrides(self, tmp_path: Path) -> None:
        """MCP sessions keep venv env without reintroducing timeout overrides."""
        venv_path = _make_venv(tmp_path)
        mock_mcp = MagicMock()
        captured_opts = self._build_and_capture(tmp_path, mcp_servers={"test": mock_mcp})

        assert captured_opts["env"]["VIRTUAL_ENV"] == str(venv_path)
        assert "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT" not in captured_opts["env"]
        assert "MCP_TOOL_TIMEOUT" not in captured_opts["env"]


class TestClaudeStreamingEnvInjection:
    """Tests for env injection in claude_streaming.stream_oauth()."""

    @pytest.mark.asyncio
    async def test_env_in_streaming_options(self, tmp_path: Path) -> None:
        """stream_oauth includes env in ClaudeAgentOptions."""
        venv_path = _make_venv(tmp_path)
        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        mock_query = AsyncMock()
        mock_query.return_value.__aiter__ = AsyncMock(return_value=iter([]))

        with (
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options),
            patch("claude_agent_sdk.query", return_value=mock_query.return_value),
        ):
            from app.adapters.claude_streaming import stream_oauth

            gen = stream_oauth(
                messages=[Message(role="user", content="test")],
                model=CLAUDE_SONNET,
                cli_path="/usr/bin/claude",
                model_map={},
                working_dir=str(tmp_path),
            )
            async for _ in gen:
                pass

        assert "env" in captured_opts
        assert captured_opts["env"]["VIRTUAL_ENV"] == str(venv_path)


class TestExtractSystemAndConversation:
    """Tests for extract_system_and_conversation()."""

    def test_system_plus_user(self) -> None:
        """System + user messages → returns (system_text, bare content without prefix)."""
        from app.adapters.claude_utils import extract_system_and_conversation

        messages = [
            Message(role="system", content="You are a pirate"),
            Message(role="user", content="Hello"),
        ]
        system_prompt, conversation = extract_system_and_conversation(messages)

        assert system_prompt == "You are a pirate"
        assert conversation == "Hello"

    def test_no_system(self) -> None:
        """User + assistant messages, no system → returns (None, conversation)."""
        from app.adapters.claude_utils import extract_system_and_conversation

        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]
        system_prompt, conversation = extract_system_and_conversation(messages)

        assert system_prompt is None
        assert "User: Hello" in conversation
        assert "Assistant: Hi there" in conversation

    def test_single_user_no_prefix(self) -> None:
        """Single user message, no system → returns (None, raw_content) without 'User: ' prefix."""
        from app.adapters.claude_utils import extract_system_and_conversation

        messages = [Message(role="user", content="What is 2+2?")]
        system_prompt, conversation = extract_system_and_conversation(messages)

        assert system_prompt is None
        assert conversation == "What is 2+2?"

    def test_multi_turn(self) -> None:
        """System + user + assistant + user → correct separation."""
        from app.adapters.claude_utils import extract_system_and_conversation

        messages = [
            Message(role="system", content="Be concise"),
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi"),
            Message(role="user", content="Bye"),
        ]
        system_prompt, conversation = extract_system_and_conversation(messages)

        assert system_prompt == "Be concise"
        assert "User: Hello" in conversation
        assert "Assistant: Hi" in conversation
        assert "User: Bye" in conversation
        assert "Be concise" not in conversation


class TestClaudeToolsMaxTurns:
    """Tests for max_turns forwarding through complete_with_tools."""

    @pytest.mark.asyncio
    async def test_max_turns_forwarded_through_tools(self, tmp_path: Path) -> None:
        """max_turns flows from complete_with_tools() → ClaudeAgentOptions."""
        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        async def mock_query(**kwargs: Any):
            return
            yield None

        with (
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options),
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.HookMatcher"),
        ):
            from app.adapters.claude_tools_helpers import complete_with_tools

            gen = complete_with_tools(
                messages=[Message(role="user", content="test")],
                model=CLAUDE_SONNET,
                tools=[],
                yolo_mode=True,
                permission_checker=None,
                working_dir=str(tmp_path),
                resume_session_id=None,
                cli_path="/usr/bin/claude",
                model_map={},
                provider_name="claude",
                max_turns=7,
            )
            try:
                async for _ in gen:
                    pass
            except Exception:
                pass

        assert captured_opts["max_turns"] == 7

    @pytest.mark.asyncio
    async def test_system_prompt_forwarded_through_tools(self, tmp_path: Path) -> None:
        """System messages are extracted and passed as system_prompt."""
        captured_opts: dict[str, Any] = {}

        def capture_options(**kwargs: Any) -> MagicMock:
            captured_opts.update(kwargs)
            return MagicMock()

        async def mock_query(**kwargs: Any):
            return
            yield None

        with (
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=capture_options),
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.HookMatcher"),
        ):
            from app.adapters.claude_tools_helpers import complete_with_tools

            gen = complete_with_tools(
                messages=[
                    Message(role="system", content="You are a pirate"),
                    Message(role="user", content="Hello"),
                ],
                model=CLAUDE_SONNET,
                tools=[],
                yolo_mode=True,
                permission_checker=None,
                working_dir=str(tmp_path),
                resume_session_id=None,
                cli_path="/usr/bin/claude",
                model_map={},
                provider_name="claude",
            )
            try:
                async for _ in gen:
                    pass
            except Exception:
                pass

        assert captured_opts["system_prompt"] == "You are a pirate"
