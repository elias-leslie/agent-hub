"""Tests for Claude adapter (OAuth-only mode)."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import Message, ProviderError
from app.adapters.claude import ClaudeAdapter
from app.adapters.claude_utils import build_claude_prompt


@pytest.fixture
def mock_cli_available() -> Generator[None]:
    """Mock shutil.which to return Claude CLI path."""
    with patch("app.adapters.claude.shutil.which", return_value="/usr/local/bin/claude"):
        yield


@pytest.fixture
def mock_no_cli() -> Generator[None]:
    """Mock shutil.which to return None (no Claude CLI)."""
    with patch("app.adapters.claude.shutil.which", return_value=None):
        yield


class TestClaudeAdapter:
    """Tests for ClaudeAdapter (OAuth-only)."""

    def test_init_with_cli(self, mock_cli_available: None) -> None:
        """Test initialization with Claude CLI available."""
        adapter = ClaudeAdapter()
        assert adapter.provider_name == "claude"
        assert adapter.auth_mode == "oauth"

    def test_init_no_cli_raises(self, mock_no_cli: None) -> None:
        """Test that missing Claude CLI raises ValueError."""
        with pytest.raises(ValueError, match="Claude adapter requires Claude CLI"):
            ClaudeAdapter()

    @pytest.mark.asyncio
    async def test_health_check_with_cli(self, mock_cli_available: None) -> None:
        """Test health check with Claude CLI available."""
        adapter = ClaudeAdapter()

        result = await adapter.health_check()
        assert result is True

    def test_health_check_no_cli(self, mock_no_cli: None) -> None:
        """Test that initialization fails without CLI."""
        with pytest.raises(ValueError):
            ClaudeAdapter()


class TestClaudeTimeout:
    """Tests for Claude OAuth timeout handling."""

    @pytest.fixture
    def mock_cli_available(self) -> Generator[None]:
        """Mock shutil.which to return Claude CLI path."""
        with patch("app.adapters.claude.shutil.which", return_value="/usr/local/bin/claude"):
            yield

    @pytest.mark.asyncio
    async def test_complete_timeout_raises_provider_error(self, mock_cli_available: None) -> None:
        """Test that timeout raises ProviderError with retriable=True."""
        adapter = ClaudeAdapter()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.query = AsyncMock(side_effect=TimeoutError())

        with patch("claude_agent_sdk.ClaudeSDKClient", return_value=mock_client):
            with pytest.raises(ProviderError) as exc_info:
                await adapter.complete(
                    [Message(role="user", content="Hello")],
                    model="claude-sonnet-4-5",
                )

            assert exc_info.value.provider == "claude"
            assert exc_info.value.retriable is True
            assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_timeout_value_is_300_seconds(self, mock_cli_available: None) -> None:
        """Test that the timeout is set to 300 seconds for agentic calls."""
        import inspect

        import app.adapters.claude_oauth as oauth_module

        source = inspect.getsource(oauth_module.complete_oauth)
        assert "timeout=300" in source or "timeout=300.0" in source


class TestBuildClaudePrompt:
    """Tests for build_claude_prompt covering single-message and multi-turn behavior.

    The single-message special case (stripping the 'User: ' prefix) is intentional:
    when there is exactly one user message and no system context, the function
    returns just the raw content so the prompt is not needlessly wrapped.
    """

    def _msg(self, role: str, content: str) -> Message:
        return Message(role=role, content=content)

    # --- single-message cases ---

    def test_single_user_message_strips_prefix(self) -> None:
        """Single user message returns raw content without 'User: ' prefix."""
        messages = [self._msg("user", "Hello world")]
        result = build_claude_prompt(messages)
        assert result == "Hello world"
        assert not result.startswith("User: ")

    def test_single_user_message_with_system_keeps_prefix(self) -> None:
        """When a system message is present the user turn keeps its 'User: ' prefix."""
        messages = [
            self._msg("system", "You are helpful."),
            self._msg("user", "Hello"),
        ]
        result = build_claude_prompt(messages)
        assert "You are helpful." in result
        assert "User: Hello" in result

    def test_single_user_message_multimodal_content(self) -> None:
        """Single user message with list content also strips the prefix."""
        msg = Message(role="user", content=[{"type": "text", "text": "Describe this"}])
        result = build_claude_prompt([msg])
        assert result == "Describe this"
        assert not result.startswith("User: ")

    # --- multi-turn cases ---

    def test_multi_turn_formats_roles(self) -> None:
        """Multiple turns include role prefixes separated by double newlines."""
        messages = [
            self._msg("user", "Hi"),
            self._msg("assistant", "Hello!"),
            self._msg("user", "How are you?"),
        ]
        result = build_claude_prompt(messages)
        assert "User: Hi" in result
        assert "Assistant: Hello!" in result
        assert "User: How are you?" in result

    def test_empty_messages_returns_hello(self) -> None:
        """Empty message list falls back to the default 'Hello' string."""
        result = build_claude_prompt([])
        assert result == "Hello"

    def test_system_only_returns_system_content(self) -> None:
        """A system-only message list returns the system content."""
        messages = [self._msg("system", "You are an assistant.")]
        result = build_claude_prompt(messages)
        assert result == "You are an assistant."
