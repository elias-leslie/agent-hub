"""MiniMax direct adapter using OpenAI-compatible base."""

from __future__ import annotations

from app.adapters.base import AuthenticationError
from app.adapters.openai_compat import OpenAICompatibleAdapter


class MinimaxAdapter(OpenAICompatibleAdapter):
    """Adapter for MiniMax models via direct API."""

    provider_prefix = "minimax"

    @property
    def provider_name(self) -> str:
        return "minimax"

    def _get_base_url(self) -> str:
        return "https://api.minimax.io/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        if not explicit_key:
            raise AuthenticationError("minimax")
        return explicit_key

    async def health_check(self) -> bool:
        """Check if MiniMax API is reachable (zero tokens consumed).

        MiniMax doesn't support /v1/models (returns 404), but a 404 still
        proves the API is reachable and credentials are accepted.
        Only connection errors and auth failures indicate the service is down.
        """
        try:
            await self._refresh_credentials()
            await self._client.models.list()
            return True
        except Exception as e:
            # 404 = endpoint unsupported but API reachable
            return hasattr(e, "status_code") and e.status_code == 404
