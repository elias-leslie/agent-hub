"""Tests for the Gemini adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderError,
    RateLimitError,
    StreamEvent,
)
from app.adapters.gemini import GeminiAdapter
from app.adapters.gemini_adapter_ops import tool_loop
from app.constants.models import GEMINI_FLASH


@pytest.fixture
def mock_genai():
    """Mock Google GenAI client."""
    with patch("app.adapters.gemini_adapter_settings.genai") as mock:
        yield mock


class TestGeminiAdapter:
    """Tests for API-key-only Gemini adapter behavior."""

    @patch("app.adapters.gemini.resolve_api_keys", return_value=[])
    def test_init_with_api_key(self, _mock_keys, mock_genai):
        """Explicit API keys should build an SDK client immediately."""
        adapter = GeminiAdapter(api_key="custom-key")

        assert adapter.provider_name == "gemini"
        assert adapter._api_keys == ["custom-key"]
        call_kwargs = mock_genai.Client.call_args.kwargs
        assert call_kwargs["api_key"] == "custom-key"
        assert "http_options" not in call_kwargs

    def test_init_from_credential_manager(self, mock_genai):
        """CredentialManager API keys should populate the failover list."""
        from app.services.credential_manager import CredentialManager

        CredentialManager.reset()
        cm = CredentialManager.get_instance()
        cm.set("gemini", "api_key", "from-cm")
        cm._initialized = True

        try:
            adapter = GeminiAdapter()
            assert adapter._api_keys == ["from-cm"]
            call_kwargs = mock_genai.Client.call_args.kwargs
            assert call_kwargs["api_key"] == "from-cm"
        finally:
            CredentialManager.reset()

    @patch("app.adapters.gemini.resolve_api_keys", return_value=[])
    @patch("app.adapters.gemini.resolve_api_key", return_value=None)
    def test_init_without_api_key_leaves_adapter_unconfigured(self, _mock_key, _mock_keys):
        """No stored API key should leave Gemini unavailable until configured."""
        adapter = GeminiAdapter()
        assert adapter._api_keys == []
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_complete_success(self, mock_genai):
        """Successful completions should map SDK response data correctly."""
        mock_response = MagicMock()
        mock_response.text = "Hello!"
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 5
        mock_response.candidates = [MagicMock(finish_reason="STOP")]

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter(api_key="test-key")
        result = await adapter.complete([Message(role="user", content="Hi")], model=GEMINI_FLASH)

        assert result.content == "Hello!"
        assert result.model == GEMINI_FLASH
        assert result.provider == "gemini"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.finish_reason == "STOP"

    @pytest.mark.asyncio
    async def test_complete_rate_limit_maps_to_adapter_error(self, mock_genai):
        """Transient quota errors should become RateLimitError."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("429 Too Many Requests"))
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter(api_key="test-key")
        with pytest.raises(RateLimitError) as exc_info:
            await adapter.complete([Message(role="user", content="Hi")], model=GEMINI_FLASH)

        assert exc_info.value.provider == "gemini"
        assert exc_info.value.retriable is True

    @pytest.mark.asyncio
    async def test_complete_auth_error_maps_to_adapter_error(self, mock_genai):
        """Authentication failures should become AuthenticationError."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("401 Invalid API key"))
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter(api_key="test-key")
        with pytest.raises(AuthenticationError) as exc_info:
            await adapter.complete([Message(role="user", content="Hi")], model=GEMINI_FLASH)

        assert exc_info.value.provider == "gemini"

    @pytest.mark.asyncio
    async def test_complete_passes_multiple_sdk_clients_to_failover(self):
        """Gemini should preserve the multi-key failover list for completions."""
        expected = CompletionResult(
            content="Second key succeeded",
            model=GEMINI_FLASH,
            provider="gemini",
            input_tokens=12,
            output_tokens=7,
        )
        client_1 = MagicMock(name="client-1")
        client_2 = MagicMock(name="client-2")

        with (
            patch("app.adapters.gemini.resolve_api_key", return_value=None),
            patch("app.adapters.gemini.resolve_api_keys", return_value=["k1", "k2"]),
            patch("app.adapters.gemini.make_sdk_client", side_effect=[client_1, client_2]),
            patch("app.adapters.gemini.sdk_complete_with_failover", new_callable=AsyncMock) as mock_failover,
        ):
            mock_failover.return_value = expected
            adapter = GeminiAdapter()
            result = await adapter.complete([Message(role="user", content="Hi")], model=GEMINI_FLASH)

        assert result.content == "Second key succeeded"
        assert mock_failover.await_args is not None
        args = mock_failover.await_args.args
        assert args[0] == [client_1, client_2]
        assert args[1] is client_1

    def test_refresh_api_key_allows_empty_key_set(self):
        """Removing Gemini keys from the DB should clear the in-memory list."""
        with (
            patch("app.adapters.gemini.resolve_api_key", return_value=None),
            patch("app.adapters.gemini.resolve_api_keys", side_effect=[["k1"], []]),
            patch("app.adapters.gemini.make_sdk_client", side_effect=[MagicMock()]),
        ):
            adapter = GeminiAdapter()
            assert adapter._api_keys == ["k1"]

            adapter._refresh_api_key()
            assert adapter._api_keys == []
            assert adapter._sdk_clients == []
            assert adapter._client is None

    @pytest.mark.asyncio
    async def test_stream_passes_multiple_sdk_clients_to_failover(self):
        """Streaming should use the same SDK-client failover pool."""
        async def fake_stream(*_args) -> AsyncIterator[StreamEvent]:
            yield StreamEvent(type="content", content="hello")
            yield StreamEvent(type="done", input_tokens=1, output_tokens=1, finish_reason="STOP")

        client_1 = MagicMock(name="client-1")
        client_2 = MagicMock(name="client-2")

        with (
            patch("app.adapters.gemini.resolve_api_key", return_value=None),
            patch("app.adapters.gemini.resolve_api_keys", return_value=["k1", "k2"]),
            patch("app.adapters.gemini.make_sdk_client", side_effect=[client_1, client_2]),
            patch("app.adapters.gemini.sdk_stream_with_failover", side_effect=fake_stream),
        ):
            adapter = GeminiAdapter()
            events = [event async for event in adapter.stream([Message(role="user", content="hi")], GEMINI_FLASH)]

        assert [event.type for event in events] == ["content", "done"]

    @pytest.mark.asyncio
    async def test_tool_loop_forwards_agent_context_kwargs(self):
        """Gemini tool loop should accept Agent Hub context kwargs."""
        captured: dict[str, object] = {}

        async def fake_execute_tool_loop(**kwargs):
            captured.update(kwargs)
            yield ("done", "session-1")

        with patch("app.adapters.gemini_adapter_ops.execute_tool_loop", side_effect=fake_execute_tool_loop):
            events = [
                event
                async for event in tool_loop(
                    MagicMock(),
                    [Message(role="user", content="hi")],
                    GEMINI_FLASH,
                    [],
                    "/tmp/project",
                    None,
                    1,
                    "gemini",
                    project_id="summitflow",
                    agent_slug="graphify-semantic-extractor",
                    tool_catalog=[],
                )
            ]

        assert events == [("done", "session-1")]
        assert captured["agent_slug"] == "graphify-semantic-extractor"
        assert captured["tool_catalog"] == []

    @pytest.mark.asyncio
    async def test_tool_loop_tries_second_key_after_retryable_failure(self):
        """Gemini tool loop should use the secondary API key on quota failures."""
        clients = [MagicMock(name="client-1"), MagicMock(name="client-2")]
        attempted: list[object] = []

        async def fake_execute_tool_loop(client, **_kwargs):
            attempted.append(client)
            if len(attempted) == 1:
                raise ProviderError("quota", provider="gemini", retriable=True)
            yield ("done", "session-2")

        with patch("app.adapters.gemini_adapter_ops.execute_tool_loop", side_effect=fake_execute_tool_loop):
            events = [
                event
                async for event in tool_loop(
                    clients,
                    [Message(role="user", content="hi")],
                    GEMINI_FLASH,
                    [],
                    "/tmp/project",
                    None,
                    1,
                    "gemini",
                    project_id="summitflow",
                )
            ]

        assert attempted == clients
        assert events == [("done", "session-2")]
