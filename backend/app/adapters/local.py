"""Local OpenAI-compatible adapter for Ollama, vLLM, or llama.cpp servers."""

from __future__ import annotations

from app.adapters.openai_compat import OpenAICompatibleAdapter
from app.config import settings


class LocalAdapter(OpenAICompatibleAdapter):
    """Adapter for local OpenAI-compatible inference endpoints."""

    provider_prefix = "local"

    @property
    def provider_name(self) -> str:
        return "local"

    def _get_base_url(self) -> str:
        return settings.local_openai_base_url.rstrip("/")

    def _get_api_key(self, explicit_key: str | None) -> str:
        return explicit_key or settings.local_openai_api_key.strip() or "local"
