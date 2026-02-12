"""Tests for OpenAICompatibleAdapter base class."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import CompletionResult, Message
from app.adapters.openai_compat import OpenAICompatibleAdapter


class ConcreteTestAdapter(OpenAICompatibleAdapter):
    """Concrete implementation for testing the base class."""

    @property
    def provider_name(self) -> str:
        return "test-provider"

    def _get_base_url(self) -> str:
        return "https://api.test-provider.com/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        return explicit_key or "test-key-from-settings"

    def _resolve_model(self, model: str) -> str:
        if model.startswith("test/"):
            return model[len("test/"):]
        return model


class TestOpenAICompatibleAdapter:
    """Tests for the OpenAI-compatible base adapter."""

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_provider_name(self, mock_openai_class: MagicMock) -> None:
        adapter = ConcreteTestAdapter(api_key="dummy")
        assert adapter.provider_name == "test-provider"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_raises_without_api_key(self, mock_openai_class: MagicMock) -> None:
        class NoKeyAdapter(OpenAICompatibleAdapter):
            @property
            def provider_name(self) -> str:
                return "nokey"

            def _get_base_url(self) -> str:
                return "https://api.example.com/v1"

            def _get_api_key(self, explicit_key: str | None) -> str:
                return explicit_key or ""

            def _resolve_model(self, model: str) -> str:
                return model

        with pytest.raises(ValueError, match="Nokey API key not configured"):
            NoKeyAdapter(api_key="")

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_model_resolution(self, mock_openai_class: MagicMock) -> None:
        adapter = ConcreteTestAdapter(api_key="dummy")
        assert adapter._resolve_model("test/gpt-5") == "gpt-5"
        assert adapter._resolve_model("raw-model") == "raw-model"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_client_created_with_base_url(self, mock_openai_class: MagicMock) -> None:
        ConcreteTestAdapter(api_key="my-key")
        mock_openai_class.assert_called_once()
        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["api_key"] == "my-key"
        assert call_kwargs["base_url"] == "https://api.test-provider.com/v1"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_convert_messages(self, mock_openai_class: MagicMock) -> None:
        adapter = ConcreteTestAdapter(api_key="dummy")
        messages = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="Hello"),
        ]
        result = adapter._convert_messages(messages)
        assert result == [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_complete_returns_result(self, mock_openai_class: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from test!"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "test-model"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_class.return_value = mock_client

        adapter = ConcreteTestAdapter(api_key="dummy")
        result = await adapter.complete(
            messages=[Message(role="user", content="Hi")],
            model="test-model",
        )

        assert isinstance(result, CompletionResult)
        assert result.content == "Hello from test!"
        assert result.provider == "test-provider"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_complete_with_tool_calls(self, mock_openai_class: MagicMock) -> None:
        mock_tc = MagicMock()
        mock_tc.id = "tc_123"
        mock_tc.function.name = "get_weather"
        mock_tc.function.arguments = '{"city": "NYC"}'

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        mock_response.choices[0].message.tool_calls = [mock_tc]
        mock_response.choices[0].finish_reason = "tool_calls"
        mock_response.model = "test-model"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_class.return_value = mock_client

        adapter = ConcreteTestAdapter(api_key="dummy")
        result = await adapter.complete(
            messages=[Message(role="user", content="Weather?")],
            model="test-model",
        )

        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].input == {"city": "NYC"}

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_health_check_success(self, mock_openai_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(return_value=MagicMock())
        mock_openai_class.return_value = mock_client

        adapter = ConcreteTestAdapter(api_key="dummy")
        result = await adapter.health_check()
        assert result is True

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_health_check_failure(self, mock_openai_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(side_effect=Exception("Connection refused"))
        mock_openai_class.return_value = mock_client

        adapter = ConcreteTestAdapter(api_key="dummy")
        result = await adapter.health_check()
        assert result is False

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_stream(self, mock_openai_class: MagicMock) -> None:
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "Hello "

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = "world"

        async def mock_stream():
            yield chunk1
            yield chunk2

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
        mock_openai_class.return_value = mock_client

        adapter = ConcreteTestAdapter(api_key="dummy")
        events = []
        async for event in adapter.stream(
            messages=[Message(role="user", content="Hi")],
            model="test-model",
        ):
            events.append(event)

        assert len(events) == 3
        assert events[0].type == "content"
        assert events[0].content == "Hello "
        assert events[1].type == "content"
        assert events[1].content == "world"
        assert events[2].type == "done"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_handle_error_auth(self, mock_openai_class: MagicMock) -> None:
        from app.adapters.base import ProviderError

        adapter = ConcreteTestAdapter(api_key="dummy")
        with pytest.raises(ProviderError) as exc_info:
            adapter._handle_error(Exception("401 Unauthorized"))
        assert exc_info.value.status_code == 401

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_handle_error_rate_limit(self, mock_openai_class: MagicMock) -> None:
        from app.adapters.base import ProviderError

        adapter = ConcreteTestAdapter(api_key="dummy")
        with pytest.raises(ProviderError) as exc_info:
            adapter._handle_error(Exception("429 Rate limit exceeded"))
        assert exc_info.value.status_code == 429
        assert exc_info.value.retriable is True
