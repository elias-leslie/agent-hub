"""Tests for xAI direct adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import ProviderError
from app.adapters.xai import XAIAdapter


class TestXAIAdapter:
    """Test cases for xAI adapter."""

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_provider_name(self, mock_openai_class: MagicMock) -> None:
        adapter = XAIAdapter(api_key="test-key")
        assert adapter.provider_name == "xai"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_base_url(self, mock_openai_class: MagicMock) -> None:
        XAIAdapter(api_key="test-key")
        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["base_url"] == "https://api.x.ai/v1"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_model_resolution_strips_prefix(self, mock_openai_class: MagicMock) -> None:
        adapter = XAIAdapter(api_key="test-key")
        assert adapter._resolve_model("xai/grok-code-fast-1") == "grok-code-fast-1"
        assert adapter._resolve_model("xai/grok-4-1-fast-reasoning") == "grok-4-1-fast-reasoning"
        assert adapter._resolve_model("xai/grok-4-1-fast-non-reasoning") == "grok-4-1-fast-reasoning"
        assert adapter._resolve_model("xai/grok-4.1-fast") == "grok-4-1-fast-reasoning"
        assert adapter._resolve_model("xai/grok-4.20") == "grok-4.20-reasoning"
        assert adapter._resolve_model("xai/grok-4.20-beta-latest-non-reasoning") == "grok-4.20-reasoning"
        assert adapter._resolve_model("xai/grok-4.20-multi-agent-beta-0309") == "grok-4.20-multi-agent"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_model_resolution_passthrough(self, mock_openai_class: MagicMock) -> None:
        adapter = XAIAdapter(api_key="test-key")
        assert adapter._resolve_model("grok-code-fast-1") == "grok-code-fast-1"

    def test_no_api_key_error(self) -> None:
        from app.adapters.base import AuthenticationError

        with pytest.raises(AuthenticationError):
            XAIAdapter(api_key="")

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_completion(self, mock_openai_class: MagicMock) -> None:
        from app.adapters.base import Message

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from Grok!"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "grok-code-fast-1"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 8
        mock_response.usage.completion_tokens = 4

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_class.return_value = mock_client

        adapter = XAIAdapter(api_key="test-key")
        result = await adapter.complete(
            messages=[Message(role="user", content="Hi")],
            model="xai/grok-code-fast-1",
            prompt_cache_key="sess-1",
        )

        assert result.content == "Hello from Grok!"
        assert result.provider == "xai"
        assert mock_client.chat.completions.create.await_args is not None
        assert mock_client.chat.completions.create.await_args.kwargs["extra_headers"] == {
            "x-grok-conv-id": "sess-1"
        }

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_multi_agent_completion_uses_responses_api(self, mock_openai_class: MagicMock) -> None:
        from app.adapters.base import Message

        mock_response = MagicMock()
        mock_response.output_text = None
        mock_response.output = [MagicMock(content=[MagicMock(text="Research complete")])]
        mock_response.model = "grok-4.20-multi-agent"
        mock_response.status = "completed"
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 12
        mock_response.usage.output_tokens = 6
        mock_response.usage.output_tokens_details = MagicMock(reasoning_tokens=9)

        mock_client = MagicMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)
        mock_openai_class.return_value = mock_client

        adapter = XAIAdapter(api_key="test-key")
        result = await adapter.complete(
            messages=[Message(role="user", content="Hi")],
            model="xai/grok-4.20-multi-agent",
            prompt_cache_key="sess-42",
        )

        assert result.content == "Research complete"
        assert result.provider == "xai"
        assert result.thinking_tokens == 9
        mock_client.responses.create.assert_awaited_once()
        assert mock_client.responses.create.await_args is not None
        assert mock_client.responses.create.await_args.kwargs["extra_headers"] == {
            "x-grok-conv-id": "sess-42"
        }
        mock_client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_multi_agent_normalizes_image_blocks_for_responses_api(self, mock_openai_class: MagicMock) -> None:
        from app.adapters.base import Message

        mock_response = MagicMock()
        mock_response.output_text = "done"
        mock_response.output = []
        mock_response.model = "grok-4.20-multi-agent"
        mock_response.status = "completed"
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 1
        mock_response.usage.output_tokens = 1
        mock_response.usage.output_tokens_details = MagicMock(reasoning_tokens=0)

        mock_client = MagicMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)
        mock_openai_class.return_value = mock_client

        adapter = XAIAdapter(api_key="test-key")
        await adapter.complete(
            messages=[
                Message(
                    role="user",
                    content=[
                        {"type": "text", "text": "Analyze"},
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
            ],
            model="xai/grok-4.20-multi-agent",
        )

        assert mock_client.responses.create.await_args is not None
        assert mock_client.responses.create.await_args.kwargs["input"] == [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Analyze"},
                    {"type": "input_image", "image_url": "data:image/png;base64,abc123"},
                ],
            }
        ]

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_multi_agent_rejects_agent_hub_client_side_tools(self, mock_openai_class: MagicMock) -> None:
        from app.adapters.base import Message

        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        adapter = XAIAdapter(api_key="test-key")
        with pytest.raises(ProviderError, match="client-side tool loops"):
            await adapter.complete(
                messages=[Message(role="user", content="Hi")],
                model="xai/grok-4.20-multi-agent",
                tools=[{"name": "bash"}],
            )

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_health_check(self, mock_openai_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(return_value=MagicMock())
        mock_openai_class.return_value = mock_client

        adapter = XAIAdapter(api_key="test-key")
        assert await adapter.health_check() is True
