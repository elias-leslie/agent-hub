"""OpenRouter adapter using OpenAI-compatible base."""

from __future__ import annotations

from typing import Any

from app.adapters.base import AuthenticationError
from app.adapters.openai_compat import OpenAICompatibleAdapter


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

    from app.constants import MODEL_ALIASES

    resolved = MODEL_ALIASES.get(model)
    if resolved and resolved.startswith("openrouter/"):
        return resolved[len("openrouter/"):]
    legacy_aliases = {
        "or/sonnet": "anthropic/claude-3.5-sonnet",
        "or/gpt4o": "openai/gpt-4o",
    }
    if model in legacy_aliases:
        return legacy_aliases[model]

    return model


class OpenRouterAdapter(OpenAICompatibleAdapter):
    """Adapter for OpenRouter models via OpenAI-compatible API."""

    @property
    def provider_name(self) -> str:
        return "openrouter"

    def _get_base_url(self) -> str:
        return "https://openrouter.ai/api/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        if not explicit_key:
            raise AuthenticationError("openrouter")
        return explicit_key

    def _get_default_headers(self) -> dict[str, str] | None:
        return {
            "HTTP-Referer": "https://agent-hub.dev",
            "X-Title": "Agent Hub",
        }

    def _resolve_model(self, model: str) -> str:
        return resolve_openrouter_model(model)

    def _get_client_kwargs(self) -> dict[str, Any]:
        return {}
