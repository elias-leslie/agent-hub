"""Tests for Claude adapter (OAuth-only mode)."""

from __future__ import annotations

from collections.abc import Generator
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import CompletionResult, Message, ProviderError, RateLimitError
from app.adapters.claude import ClaudeAdapter
from app.adapters.claude_direct import (
    _apply_optional_create_kwargs,
    _build_create_kwargs,
    _create_with_temperature_retry,
    _raise_direct_api_error,
)
from app.adapters.claude_oauth import complete_oauth
from app.adapters.claude_utils import build_claude_prompt
from app.constants.models import CLAUDE_SONNET


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
        """Test initialization with Claude CLI available (no OAuth token)."""
        mock_cm = MagicMock()
        mock_cm.get.return_value = None
        with patch("app.services.credential_manager.get_credential_manager", return_value=mock_cm):
            adapter = ClaudeAdapter()
            assert adapter.provider_name == "claude"
            assert adapter.auth_mode == "cli"

    def test_init_no_cli_raises(self, mock_no_cli: None) -> None:
        """Test that missing Claude CLI, no OAuth token, and no API key raises ValueError."""
        mock_cm = MagicMock()
        mock_cm.get.return_value = None
        mock_cm.get_api_key.return_value = None
        with (
            patch("app.services.credential_manager.get_credential_manager", return_value=mock_cm),
            pytest.raises(ValueError, match="Claude adapter requires"),
        ):
            ClaudeAdapter()

    @pytest.mark.asyncio
    async def test_health_check_with_cli(self, mock_cli_available: None) -> None:
        """Test health check with Claude CLI available."""
        mock_cm = MagicMock()
        mock_cm.get.return_value = None
        with patch("app.services.credential_manager.get_credential_manager", return_value=mock_cm):
            adapter = ClaudeAdapter()
            result = await adapter.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_complete_uses_direct_api_for_vision_with_cli_available(
        self,
        mock_cli_available: None,
    ) -> None:
        """Claude CLI is text-only; vision content should use direct API when credentials exist."""
        mock_cm = MagicMock()
        mock_cm.get.return_value = "oauth-token"
        mock_cm.get_api_key.return_value = None
        direct_result = CompletionResult(
            content="{}",
            model=CLAUDE_SONNET,
            provider="claude",
            input_tokens=1,
            output_tokens=1,
        )
        with (
            patch("app.services.credential_manager.get_credential_manager", return_value=mock_cm),
            patch("app.adapters.claude.complete_direct", new_callable=AsyncMock, return_value=direct_result) as direct,
            patch("app.adapters.claude.complete_oauth", new_callable=AsyncMock) as oauth,
        ):
            adapter = ClaudeAdapter()
            result = await adapter.complete(
                [
                    Message(
                        role="user",
                        content=[
                            {"type": "text", "text": "Read this image."},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": "abc",
                                },
                            },
                        ],
                    )
                ],
                model=CLAUDE_SONNET,
            )

        assert result is direct_result
        direct.assert_awaited_once()
        oauth.assert_not_called()

    def test_health_check_no_cli(self, mock_no_cli: None) -> None:
        """Test that initialization fails without CLI, no token, and no API key."""
        mock_cm = MagicMock()
        mock_cm.get.return_value = None
        mock_cm.get_api_key.return_value = None
        with (
            patch("app.services.credential_manager.get_credential_manager", return_value=mock_cm),
            pytest.raises(ValueError),
        ):
            ClaudeAdapter()


class TestClaudeDirectApi:
    """Tests for direct Anthropic API request shaping."""

    def test_build_create_kwargs_omits_deprecated_temperature_for_opus_47(self) -> None:
        kwargs = _build_create_kwargs("claude-opus-4-7", [], "", 4096, 0.1, "none")
        assert "temperature" not in kwargs

    def test_build_create_kwargs_keeps_temperature_for_supported_models(self) -> None:
        kwargs = _build_create_kwargs("claude-sonnet-4-6", [], "", 4096, 0.1, "none")
        assert kwargs["temperature"] == 0.1

    def test_apply_optional_create_kwargs_adds_thinking_to_non_stream_calls(self) -> None:
        kwargs = {"model": "claude-opus-4-7", "messages": [], "max_tokens": 6000}
        _apply_optional_create_kwargs(kwargs, {"thinking_level": "high"})
        assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 4096}

    @pytest.mark.asyncio
    async def test_create_retries_without_deprecated_temperature(self) -> None:
        response = object()

        class FakeMessages:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            async def create(self, **kwargs: object) -> object:
                self.calls.append(kwargs)
                if len(self.calls) == 1:
                    raise Exception("`temperature` is deprecated for this model.")
                return response

        class FakeClient:
            def __init__(self) -> None:
                self.messages = FakeMessages()

        client = FakeClient()
        result = await _create_with_temperature_retry(
            client,
            {"model": "claude-new", "messages": [], "temperature": 0.1},
        )

        assert result is response
        assert client.messages.calls[0]["temperature"] == 0.1
        assert "temperature" not in client.messages.calls[1]

    def test_direct_api_rate_limit_maps_to_router_rate_limit(self) -> None:
        class FakeRateLimit(Exception):
            status_code = 429

        with pytest.raises(RateLimitError) as exc_info:
            _raise_direct_api_error(FakeRateLimit("limited"), "claude")

        assert exc_info.value.provider == "claude"
        assert exc_info.value.status_code == 429


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
                    model=CLAUDE_SONNET,
                )

            assert exc_info.value.provider == "claude"
            assert exc_info.value.retriable is True
            assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_complete_does_not_hardcode_300s_timeout(self, mock_cli_available: None) -> None:
        """Claude CLI completions should not add a local hardcoded 300s timeout."""
        import inspect

        import app.adapters.claude_oauth as oauth_module

        source = inspect.getsource(oauth_module.complete_oauth)
        assert "timeout=300" not in source
        assert "timeout=300.0" not in source


class TestClaudeOAuthLimitHandling:
    """Tests for Claude OAuth rate-limit classification."""

    @pytest.mark.asyncio
    async def test_complete_oauth_raises_rate_limit_for_usage_limit_banner(self) -> None:
        """A Claude usage-limit banner should trigger fallback, not a fake success."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.query = AsyncMock(return_value=None)
        fake_sdk_module = ModuleType("claude_agent_sdk")
        fake_sdk_module.ClaudeSDKClient = MagicMock(return_value=mock_client)  # type: ignore[attr-defined]

        async def fake_process_response_stream(
            client: object,
            content_parts: list[str],
            thinking_parts: list[str],
        ) -> tuple[dict[str, object] | None, dict[str, object] | None, object | None]:
            del client, thinking_parts
            content_parts.append("You've hit your limit - resets 11pm (UTC)")
            return None, {"output_tokens": 10}, None

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk_module}),
            patch("app.adapters.claude_oauth.build_sdk_options", return_value=(object(), None)),
            patch("app.adapters.claude_oauth._process_response_stream", side_effect=fake_process_response_stream),
            pytest.raises(RateLimitError) as exc_info,
        ):
            await complete_oauth(
                messages=[Message(role="user", content="Hello")],
                model=CLAUDE_SONNET,
                cli_path="/usr/local/bin/claude",
                model_map={CLAUDE_SONNET: "sonnet-4-6"},
                provider_name="claude",
            )

        assert exc_info.value.provider == "claude"
        assert exc_info.value.quota_details == {"message": "You've hit your limit - resets 11pm (UTC)"}


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
