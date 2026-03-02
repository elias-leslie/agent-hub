"""OpenAI direct adapter using OpenAI-compatible base."""

from __future__ import annotations

from app.adapters.base import AuthenticationError
from app.adapters.openai_compat import OpenAICompatibleAdapter


class OpenAIAdapter(OpenAICompatibleAdapter):
    """Adapter for OpenAI models via direct API."""

    provider_prefix = "openai"

    @property
    def provider_name(self) -> str:
        return "openai"

    def _get_base_url(self) -> str:
        return "https://api.openai.com/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        if not explicit_key:
            raise AuthenticationError("openai")
        return explicit_key
