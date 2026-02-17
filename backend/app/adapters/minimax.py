"""MiniMax direct adapter using OpenAI-compatible base."""

from __future__ import annotations

from app.adapters.openai_compat import OpenAICompatibleAdapter
from app.config import settings


class MinimaxAdapter(OpenAICompatibleAdapter):
    """Adapter for MiniMax models via direct API."""

    provider_prefix = "minimax"

    @property
    def provider_name(self) -> str:
        return "minimax"

    def _get_base_url(self) -> str:
        return "https://api.minimax.io/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        return explicit_key or settings.minimax_api_key
