"""NVIDIA NIM adapter using OpenAI-compatible base."""

from __future__ import annotations

from app.adapters.openai_compat import OpenAICompatibleAdapter
from app.config import settings


class NvidiaAdapter(OpenAICompatibleAdapter):
    """Adapter for NVIDIA NIM models via OpenAI-compatible API."""

    provider_prefix = "nvidia"

    @property
    def provider_name(self) -> str:
        return "nvidia"

    def _get_base_url(self) -> str:
        return "https://integrate.api.nvidia.com/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        return explicit_key or settings.nvidia_api_key
