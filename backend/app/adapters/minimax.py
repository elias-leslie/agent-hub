"""MiniMax direct adapter using OpenAI-compatible base."""

from __future__ import annotations

from app.adapters.openai_compat import OpenAICompatibleAdapter
from app.config import settings


class MinimaxAdapter(OpenAICompatibleAdapter):
    """Adapter for MiniMax models via direct API."""

    @property
    def provider_name(self) -> str:
        return "minimax"

    def _get_base_url(self) -> str:
        return "https://api.minimax.io/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        return explicit_key or settings.minimax_api_key

    def _resolve_model(self, model: str) -> str:
        if model.startswith("minimax/"):
            return model[len("minimax/") :]
        return model
