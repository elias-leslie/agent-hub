"""DeepSeek direct adapter using OpenAI-compatible base."""

from __future__ import annotations

from app.adapters.base import AuthenticationError
from app.adapters.openai_compat import OpenAICompatibleAdapter


class DeepSeekAdapter(OpenAICompatibleAdapter):
    """Adapter for DeepSeek models via direct API."""

    provider_prefix = "deepseek"

    @property
    def provider_name(self) -> str:
        return "deepseek"

    def _get_base_url(self) -> str:
        return "https://api.deepseek.com"

    def _get_api_key(self, explicit_key: str | None) -> str:
        if not explicit_key:
            raise AuthenticationError("deepseek")
        return explicit_key
