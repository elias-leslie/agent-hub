"""Tests for OpenAI direct adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.openai import OpenAIAdapter


class TestOpenAIAdapter:
    """Test cases for OpenAI adapter."""

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_provider_name(self, mock_openai_class: MagicMock) -> None:
        adapter = OpenAIAdapter(api_key="test-key")
        assert adapter.provider_name == "openai"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_base_url(self, mock_openai_class: MagicMock) -> None:
        OpenAIAdapter(api_key="test-key")
        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["base_url"] == "https://api.openai.com/v1"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_model_resolution_strips_prefix(self, mock_openai_class: MagicMock) -> None:
        adapter = OpenAIAdapter(api_key="test-key")
        assert adapter._resolve_model("openai/gpt-5.2") == "gpt-5.2"
        assert adapter._resolve_model("openai/gpt-5.3-codex") == "gpt-5.3-codex"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_model_resolution_passthrough(self, mock_openai_class: MagicMock) -> None:
        adapter = OpenAIAdapter(api_key="test-key")
        assert adapter._resolve_model("gpt-5.2") == "gpt-5.2"

    @patch("app.adapters.openai.settings")
    def test_no_api_key_error(self, mock_settings: MagicMock) -> None:
        mock_settings.openai_api_key = ""
        with pytest.raises(ValueError, match="Openai API key not configured"):
            OpenAIAdapter(api_key="")

    @patch("app.adapters.openai.settings")
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_uses_settings_key(self, mock_openai_class: MagicMock, mock_settings: MagicMock) -> None:
        mock_settings.openai_api_key = "from-settings"
        OpenAIAdapter()
        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["api_key"] == "from-settings"

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_completion(self, mock_openai_class: MagicMock) -> None:
        from app.adapters.base import Message

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from GPT!"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "gpt-5.2"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_class.return_value = mock_client

        adapter = OpenAIAdapter(api_key="test-key")
        result = await adapter.complete(
            messages=[Message(role="user", content="Hi")],
            model="openai/gpt-5.2",
        )

        assert result.content == "Hello from GPT!"
        assert result.provider == "openai"

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_health_check(self, mock_openai_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(return_value=MagicMock())
        mock_openai_class.return_value = mock_client

        adapter = OpenAIAdapter(api_key="test-key")
        assert await adapter.health_check() is True
