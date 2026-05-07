"""NVIDIA NIM adapter using OpenAI-compatible base."""

from __future__ import annotations

from app.adapters.base import AuthenticationError
from app.adapters.openai_compat import OpenAICompatibleAdapter

# Map our internal model IDs (nvidia/<short>) to NVIDIA's vendor-namespaced IDs.
# NVIDIA NIM uses the original vendor namespace, not a flat nvidia/ prefix.
_NVIDIA_MODEL_MAP: dict[str, str] = {
    "qwen3.5-397b-a17b": "qwen/qwen3.5-397b-a17b",
    "deepseek-v4-flash": "deepseek-ai/deepseek-v4-flash",
    "kimi-k2.6": "moonshotai/kimi-k2.6",
    "kimi-k2.5": "moonshotai/kimi-k2.5",
    "minimax-m2.7": "minimaxai/minimax-m2.7",
    "minimax-m2.5": "minimaxai/minimax-m2.5",
}


class NvidiaAdapter(OpenAICompatibleAdapter):
    """Adapter for NVIDIA NIM models via OpenAI-compatible API."""

    provider_prefix = "nvidia"

    @property
    def provider_name(self) -> str:
        return "nvidia"

    def _get_base_url(self) -> str:
        return "https://integrate.api.nvidia.com/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        if not explicit_key:
            raise AuthenticationError("nvidia")
        return explicit_key

    def _resolve_model(self, model: str) -> str:
        """Map nvidia/<short> IDs to vendor-namespaced IDs for the NVIDIA API."""
        # Strip our nvidia/ prefix first
        short = model.removeprefix("nvidia/") if model.startswith("nvidia/") else model
        return _NVIDIA_MODEL_MAP.get(short, short)
