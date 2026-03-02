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
        """Check if MiniMax API is reachable.

        MiniMax doesn't support the /v1/models endpoint (returns 404),
        so we use a minimal completion request with max_tokens=1 instead.
        """
        try:
            self._refresh_credentials()
            await self._client.chat.completions.create(
                model="MiniMax-M2.5",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
            return True
        except Exception:
            return False
