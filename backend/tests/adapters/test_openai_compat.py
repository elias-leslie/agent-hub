"""Tests for OpenAICompatibleAdapter base class."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters._openai_compat_helpers import (
    convert_messages,
    handle_provider_error,
    normalize_responses_content,
)
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

    def test_convert_messages(self) -> None:
        messages = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="Hello"),
        ]
        result = convert_messages(messages)
        assert result == [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]

    def test_convert_messages_normalizes_multimodal_for_chat(self) -> None:
        messages = [
            Message(
                role="user",
                content=[
                    {"type": "text", "text": "Look"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "abc123",
                        },
                    },
                ],
            ),
        ]

        result = convert_messages(messages)

        assert result == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
                ],
            }
        ]

    def test_normalize_responses_content_maps_text_and_image_blocks(self) -> None:
        content = normalize_responses_content(
            "user",
            [
                {"type": "text", "text": "Look"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "abc123",
                    },
                },
            ],
        )

        assert content == [
            {"type": "input_text", "text": "Look"},
            {"type": "input_image", "image_url": "data:image/png;base64,abc123"},
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
    async def test_complete_with_tools_yields_tool_result(self, mock_openai_class: MagicMock) -> None:
        """Verify complete_with_tools yields both tool_use and tool_result events."""
        mock_tc = MagicMock()
        mock_tc.id = "tc_456"
        mock_tc.function.name = "bash"
        mock_tc.function.arguments = '{"command": "echo hi"}'

        # First call: returns tool call
        tool_response = MagicMock()
        tool_response.choices = [MagicMock()]
        tool_response.choices[0].message.content = ""
        tool_response.choices[0].message.tool_calls = [mock_tc]
        tool_response.choices[0].finish_reason = "tool_calls"
        tool_response.model = "test-model"
        tool_response.usage = MagicMock()
        tool_response.usage.prompt_tokens = 10
        tool_response.usage.completion_tokens = 5

        # Second call: no tool calls (done)
        final_response = MagicMock()
        final_response.choices = [MagicMock()]
        final_response.choices[0].message.content = "Done!"
        final_response.choices[0].message.tool_calls = None
        final_response.choices[0].finish_reason = "stop"
        final_response.model = "test-model"
        final_response.usage = MagicMock()
        final_response.usage.prompt_tokens = 20
        final_response.usage.completion_tokens = 3

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[tool_response, final_response]
        )
        mock_openai_class.return_value = mock_client

        adapter = ConcreteTestAdapter(api_key="dummy")

        async def fake_tool_handler(name: str, inp: dict) -> str:
            return "hi\n"

        events = []
        async for event in adapter.complete_with_tools(
            messages=[Message(role="user", content="Run echo hi")],
            model="test-model",
            tools=[{"type": "function", "function": {"name": "bash"}}],
            tool_handler=fake_tool_handler,
            max_turns=5,
        ):
            events.append(event)

        event_types = [e.type for e in events]
        assert "tool_use" in event_types, f"Expected tool_use in {event_types}"
        assert "tool_result" in event_types, f"Expected tool_result in {event_types}"
        assert "done" in event_types, f"Expected done in {event_types}"

        # tool_result should come after tool_use
        tool_use_idx = event_types.index("tool_use")
        tool_result_idx = event_types.index("tool_result")
        assert tool_result_idx > tool_use_idx

        # Verify tool_result has correct content
        tool_result_event = events[tool_result_idx]
        assert tool_result_event.tool_id == "tc_456"
        assert tool_result_event.content == "hi\n"

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_complete_with_tools_retries_empty_final_response_once(
        self, mock_openai_class: MagicMock
    ) -> None:
        mock_tc = MagicMock()
        mock_tc.id = "tc_789"
        mock_tc.function.name = "bash"
        mock_tc.function.arguments = '{"command": "echo hi"}'

        tool_response = MagicMock()
        tool_response.choices = [MagicMock()]
        tool_response.choices[0].message.content = ""
        tool_response.choices[0].message.tool_calls = [mock_tc]
        tool_response.choices[0].finish_reason = "tool_calls"
        tool_response.model = "test-model"
        tool_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

        empty_final = MagicMock()
        empty_final.choices = [MagicMock()]
        empty_final.choices[0].message.content = ""
        empty_final.choices[0].message.tool_calls = None
        empty_final.choices[0].finish_reason = "stop"
        empty_final.model = "test-model"
        empty_final.usage = MagicMock(prompt_tokens=20, completion_tokens=1)

        text_final = MagicMock()
        text_final.choices = [MagicMock()]
        text_final.choices[0].message.content = "No further changes needed."
        text_final.choices[0].message.tool_calls = None
        text_final.choices[0].finish_reason = "stop"
        text_final.model = "test-model"
        text_final.usage = MagicMock(prompt_tokens=22, completion_tokens=4)

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[tool_response, empty_final, text_final]
        )
        mock_openai_class.return_value = mock_client

        adapter = ConcreteTestAdapter(api_key="dummy")

        async def fake_tool_handler(name: str, inp: dict) -> str:
            return "hi\n"

        events = []
        async for event in adapter.complete_with_tools(
            messages=[Message(role="user", content="Run echo hi")],
            model="test-model",
            tools=[{"type": "function", "function": {"name": "bash"}}],
            tool_handler=fake_tool_handler,
            max_turns=5,
        ):
            events.append(event)

        event_types = [e.type for e in events]
        assert event_types.count("done") == 1
        assert any(e.type == "content" and e.content == "No further changes needed." for e in events)
        assert mock_client.chat.completions.create.await_count == 3

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

    def test_handle_error_auth(self) -> None:
        from app.adapters.base import ProviderError

        with pytest.raises(ProviderError) as exc_info:
            handle_provider_error(Exception("401 Unauthorized"), "test-provider")
        assert exc_info.value.status_code == 401

    def test_handle_error_rate_limit(self) -> None:
        from app.adapters.base import ProviderError

        with pytest.raises(ProviderError) as exc_info:
            handle_provider_error(Exception("429 Rate limit exceeded"), "test-provider")
        assert exc_info.value.status_code == 429
        assert exc_info.value.retriable is True
