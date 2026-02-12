"""OpenRouter adapter using OpenAI-compatible base."""

from __future__ import annotations

from typing import Any

from app.adapters.openai_compat import OpenAICompatibleAdapter
from app.config import settings
from app.constants import MODEL_ALIASES

# Build OpenRouter alias -> API model ID mapping from the central registry.
# Registry IDs are like "openrouter/x-ai/grok-code-fast-1" but the OpenRouter API
# expects "x-ai/grok-code-fast-1" (no openrouter/ prefix).
_OR_ALIAS_MAP: dict[str, str] = {}
for _alias, _model_id in MODEL_ALIASES.items():
    if _model_id.startswith("openrouter/"):
        _OR_ALIAS_MAP[_alias] = _model_id[len("openrouter/"):]

# Legacy aliases not in the registry
_OR_ALIAS_MAP["or/sonnet"] = "anthropic/claude-3.5-sonnet"
_OR_ALIAS_MAP["or/gpt4o"] = "openai/gpt-4o"


def resolve_openrouter_model(model: str) -> str:
    """Resolve model alias to OpenRouter model ID.

    Handles:
    - openrouter/provider/model -> provider/model (prefix strip)
    - or/alias -> mapped from MODEL_ALIASES registry
    - passthrough for unrecognized models
    """
    # Strip openrouter/ prefix if present
    if model.startswith("openrouter/"):
        return model[len("openrouter/"):]

    # Check alias map (derived from constants.MODEL_ALIASES)
    if model in _OR_ALIAS_MAP:
        return _OR_ALIAS_MAP[model]

    return model


class OpenRouterAdapter(OpenAICompatibleAdapter):
    """Adapter for OpenRouter models via OpenAI-compatible API."""

    @property
    def provider_name(self) -> str:
        return "openrouter"

    def _get_base_url(self) -> str:
        return "https://openrouter.ai/api/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        return explicit_key or settings.openrouter_api_key

    def _get_default_headers(self) -> dict[str, str] | None:
        return {
            "HTTP-Referer": "https://agent-hub.dev",
            "X-Title": "Agent Hub",
        }

    def _resolve_model(self, model: str) -> str:
        return resolve_openrouter_model(model)

    def _get_client_kwargs(self) -> dict[str, Any]:
        return {}
