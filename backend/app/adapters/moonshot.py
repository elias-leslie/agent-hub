"""Moonshot/Kimi direct adapter using OpenAI-compatible base."""

from __future__ import annotations

from app.adapters.base import AuthenticationError
from app.adapters.openai_compat import OpenAICompatibleAdapter


class MoonshotAdapter(OpenAICompatibleAdapter):
    """Adapter for Moonshot Kimi models via direct API."""

    provider_prefix = "moonshot"

    @property
    def provider_name(self) -> str:
        return "moonshot"

    def _get_base_url(self) -> str:
        return "https://api.moonshot.ai/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        if not explicit_key:
            raise AuthenticationError("moonshot")
        return explicit_key
