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
        pass
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

        Tries models.list() first. If CF returns 404 for that endpoint,
        we still treat it as reachable (the API responded).
        """
        try:
            await self._client.models.list()
            return True
        except Exception as e:
            # 404 = endpoint unsupported but API reachable
            return hasattr(e, "status_code") and e.status_code == 404
