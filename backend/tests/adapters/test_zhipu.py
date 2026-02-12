"""Tests for Zhipu AI direct adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.zhipu import ZhipuAdapter


class TestZhipuAdapter:
    """Test cases for Zhipu adapter."""

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_provider_name(self, mock_openai_class: MagicMock) -> None:
        adapter = ZhipuAdapter(api_key="test-key")
        assert adapter.provider_name == "zhipu"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_base_url(self, mock_openai_class: MagicMock) -> None:
        ZhipuAdapter(api_key="test-key")
        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["base_url"] == "https://open.bigmodel.cn/api/paas/v4"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_model_resolution_strips_prefix(self, mock_openai_class: MagicMock) -> None:
        adapter = ZhipuAdapter(api_key="test-key")
        assert adapter._resolve_model("zhipu/glm-5") == "glm-5"
        assert adapter._resolve_model("zhipu/glm-4.7") == "glm-4.7"

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_model_resolution_passthrough(self, mock_openai_class: MagicMock) -> None:
        adapter = ZhipuAdapter(api_key="test-key")
        assert adapter._resolve_model("glm-5") == "glm-5"

    @patch("app.adapters.zhipu.settings")
    def test_no_api_key_error(self, mock_settings: MagicMock) -> None:
        mock_settings.zhipu_api_key = ""
        with pytest.raises(ValueError, match="Zhipu API key not configured"):
            ZhipuAdapter(api_key="")

    @patch("app.adapters.zhipu.settings")
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_uses_settings_key(self, mock_openai_class: MagicMock, mock_settings: MagicMock) -> None:
        mock_settings.zhipu_api_key = "from-settings"
        ZhipuAdapter()
        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["api_key"] == "from-settings"

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_completion(self, mock_openai_class: MagicMock) -> None:
        from app.adapters.base import Message

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from GLM!"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "glm-5"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 8
        mock_response.usage.completion_tokens = 4

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_class.return_value = mock_client

        adapter = ZhipuAdapter(api_key="test-key")
        result = await adapter.complete(
            messages=[Message(role="user", content="Hi")],
            model="zhipu/glm-5",
        )

        assert result.content == "Hello from GLM!"
        assert result.provider == "zhipu"

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_health_check(self, mock_openai_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(return_value=MagicMock())
        mock_openai_class.return_value = mock_client

        adapter = ZhipuAdapter(api_key="test-key")
        assert await adapter.health_check() is True
