"""Cloudflare Workers AI adapter using OpenAI-compatible base.

Cloudflare exposes an OpenAI-compatible endpoint at:
  https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/v1

Requires two credentials via CredentialManager:
  cloudflare/account_id  — Cloudflare Account ID
  cloudflare/api_key     — Cloudflare API Token (Workers AI scope)
"""

from __future__ import annotations

import logging

from app.adapters.base import AuthenticationError
from app.adapters.openai_compat import OpenAICompatibleAdapter

logger = logging.getLogger(__name__)

# Map our internal model IDs (cloudflare/<short>) to Cloudflare's @cf/ namespaced IDs.
_CLOUDFLARE_MODEL_MAP: dict[str, str] = {
    "llama-4-scout-17b": "@cf/meta/llama-4-scout-17b-16e-instruct",
    "qwen3-30b": "@cf/qwen/qwen3-30b-a3b-fp8",
    "qwq-32b": "@cf/qwen/qwq-32b",
    "mistral-small-3.1-24b": "@cf/mistralai/mistral-small-3.1-24b-instruct",
    "qwen2.5-coder-32b": "@cf/qwen/qwen2.5-coder-32b-instruct",
    "glm-4.7-flash": "@cf/zai-org/glm-4.7-flash",
    "kimi-k2.6": "@cf/moonshotai/kimi-k2.6",
    "kimi-k2.5": "@cf/moonshotai/kimi-k2.5",
    "gpt-oss-120b": "@cf/openai/gpt-oss-120b",
    "gpt-oss-20b": "@cf/openai/gpt-oss-20b",
    "gemma-4-26b": "@cf/google/gemma-4-26b-a4b-it",
    "granite-4.0-h-micro": "@cf/ibm-granite/granite-4.0-h-micro",
    "nemotron-3-120b": "@cf/nvidia/nemotron-3-120b-a12b",
}


def _resolve_account_id() -> str:
    """Resolve the Cloudflare account ID from CredentialManager."""
    try:
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        if cm.is_initialized:
            account_id = cm.get("cloudflare", "account_id")
            if account_id:
                return account_id
    except Exception:
        logger.debug("Cloudflare credential lookup failed", exc_info=True)
    raise AuthenticationError("cloudflare")


class CloudflareAdapter(OpenAICompatibleAdapter):
    """Adapter for Cloudflare Workers AI models via OpenAI-compatible API."""

    provider_prefix = "cloudflare"

    def __init__(self, api_key: str | None = None) -> None:
        # Resolve account_id before super().__init__ needs _get_base_url
        self._account_id = _resolve_account_id()
        super().__init__(api_key)

    @property
    def provider_name(self) -> str:
        return "cloudflare"

    def _get_base_url(self) -> str:
        return f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}/ai/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        if not explicit_key:
            raise AuthenticationError("cloudflare")
        return explicit_key

    def _resolve_model(self, model: str) -> str:
        """Map cloudflare/<short> IDs to @cf/ namespaced IDs for the API."""
        short = model.removeprefix("cloudflare/") if model.startswith("cloudflare/") else model
        return _CLOUDFLARE_MODEL_MAP.get(short, short)

    async def health_check(self) -> bool:
        """Check if the Cloudflare Workers AI API is reachable (zero tokens consumed).

        Tries models.list(). Any HTTP response (including error status codes)
        means the API is reachable — only network/connection failures are "down".
        """
        try:
            await self._client.models.list()
            return True
        except Exception as e:
            # Any HTTP response (4xx/5xx) means API is reachable;
            # only connection/network errors are genuinely unreachable
            return hasattr(e, "status_code")
