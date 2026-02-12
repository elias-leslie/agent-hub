"""xAI direct adapter using OpenAI-compatible base."""

from __future__ import annotations

from app.adapters.openai_compat import OpenAICompatibleAdapter
from app.config import settings


class XAIAdapter(OpenAICompatibleAdapter):
    """Adapter for xAI (Grok) models via direct API."""

    @property
    def provider_name(self) -> str:
        return "xai"

    def _get_base_url(self) -> str:
        return "https://api.x.ai/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        return explicit_key or settings.xai_api_key

    def _resolve_model(self, model: str) -> str:
        if model.startswith("xai/"):
            return model[len("xai/"):]
        return model
