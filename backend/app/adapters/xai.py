"""xAI direct adapter using OpenAI-compatible base."""

from __future__ import annotations

from app.adapters.base import AuthenticationError
from app.adapters.openai_compat import OpenAICompatibleAdapter

_XAI_MODEL_NORMALIZATION = {
    "grok-4.1-fast": "grok-4-1-fast-reasoning",
    "grok-4-1-fast": "grok-4-1-fast-reasoning",
    "grok-4-1-fast-non-reasoning": "grok-4-1-fast-reasoning",
}


class XAIAdapter(OpenAICompatibleAdapter):
    """Adapter for xAI (Grok) models via direct API."""

    provider_prefix = "xai"

    @property
    def provider_name(self) -> str:
        return "xai"

    def _get_base_url(self) -> str:
        return "https://api.x.ai/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        if not explicit_key:
            raise AuthenticationError("xai")
        return explicit_key

    def _resolve_model(self, model: str) -> str:
        """Normalize legacy Grok model IDs before sending them to xAI."""
        resolved = super()._resolve_model(model)
        return _XAI_MODEL_NORMALIZATION.get(resolved, resolved)
