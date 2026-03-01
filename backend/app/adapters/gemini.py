"""Gemini adapter using Google GenAI SDK (API key) or CloudCode PA (OAuth).

When the primary auth mode is OAuth and a request hits a rate limit (429),
the adapter automatically falls back to the SDK client (API key) for that
request if a Gemini API key is available.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.adapters._errors_types import ProviderError
from app.adapters.base import CompletionResult, Message, ProviderAdapter, StreamEvent
from app.adapters.gemini_adapter_ops import (
    cloudcode_health_check,
    sdk_complete,
    sdk_health_check,
    tool_loop,
)
from app.adapters.gemini_adapter_settings import (
    GeminiSettings,
    get_gemini_auth_preference,
    get_gemini_vertex_project,
    make_cloudcode_client,
    make_sdk_client,
    pick_auth_mode,
    resolve_oauth_data,
    set_gemini_auth_preference,
    set_gemini_vertex_project,
)
from app.adapters.gemini_adapter_stream import sdk_stream
from app.adapters.gemini_cloudcode import cloudcode_complete, cloudcode_stream
from app.adapters.gemini_utils import resolve_api_key
from app.config import settings

logger = logging.getLogger(__name__)

# Backward-compat alias (cloudcode_claude_auth imports _resolve_oauth_data)
_resolve_oauth_data = resolve_oauth_data


class GeminiAdapter(ProviderAdapter):
    """Adapter for Gemini models.

    - API key / ADC mode: Uses the Google GenAI SDK (``genai.Client``).
    - OAuth mode: Uses raw HTTP to ``cloudcode-pa.googleapis.com`` via
      :class:`CloudCodeClient` — the same endpoint the Gemini CLI uses,
      which routes through a consumer subscription (zero per-token cost).
    """

    def __init__(
        self,
        api_key: str | None = None,
        after_tool_callback: (
            Callable[[str, dict[str, Any], str, int | None], Awaitable[None]] | None
        ) = None,
    ):
        resolved_key = resolve_api_key(api_key) or settings.gemini_api_key
        oauth_data = resolve_oauth_data()
        self._auth_mode, self._client, self._cc_client = pick_auth_mode(
            resolved_key, oauth_data, get_gemini_auth_preference(),
        )
        self._last_api_key = resolved_key
        self._oauth_project = oauth_data.get("project_id") if oauth_data else None

        # Keep an SDK client ready for API-key fallback when OAuth is rate-limited.
        # If primary mode is OAuth and we have an API key, create the SDK client
        # eagerly so it's available for fallback without extra latency.
        if self._auth_mode == "oauth" and resolved_key and self._client is None:
            self._client = make_sdk_client(resolved_key)
            logger.info(
                "Gemini adapter: OAuth primary with API-key fallback available",
            )

        logger.info(
            "Gemini adapter initialized with %s auth (preference=%s)",
            self._auth_mode, get_gemini_auth_preference(),
        )
        self._after_tool_callback = after_tool_callback

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _refresh_api_key(self) -> None:
        """Refresh API key from CredentialManager if rotated."""
        fresh = resolve_api_key(None) or settings.gemini_api_key
        if fresh and fresh != self._last_api_key:
            self._client = make_sdk_client(fresh)
            self._last_api_key = fresh
            logger.debug("Gemini: credential refreshed from cache")

    def _refresh_oauth(self) -> None:
        """Push fresher OAuth tokens from CredentialManager into CloudCodeClient."""
        oauth_data = resolve_oauth_data()
        if not (oauth_data and oauth_data.get("access_token") and oauth_data.get("project_id")):
            return
        if self._cc_client is not None:
            self._cc_client.access_token = oauth_data["access_token"]
            self._cc_client.project_id = oauth_data["project_id"]
            if oauth_data.get("refresh_token"):
                self._cc_client.refresh_token = oauth_data["refresh_token"]
            if oauth_data.get("expires_at"):
                self._cc_client.expires_at = oauth_data["expires_at"]
        else:
            self._cc_client = make_cloudcode_client(oauth_data)

    def _refresh_credentials(self) -> None:
        """Re-check CredentialManager for rotated credentials."""
        try:
            if self._auth_mode == "api_key":
                self._refresh_api_key()
            elif self._auth_mode == "oauth":
                self._refresh_oauth()
        except Exception:
            pass

    def _has_api_key_fallback(self) -> bool:
        """True if we're in OAuth mode but have an SDK client for fallback."""
        return self._auth_mode == "oauth" and self._client is not None

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion using Gemini API."""
        self._refresh_credentials()
        if self._auth_mode == "oauth" and self._cc_client is not None:
            try:
                return await cloudcode_complete(
                    self._cc_client, messages, model, temperature,
                    max_tokens, self.provider_name, kwargs,
                )
            except ProviderError as e:
                if e.retriable and self._has_api_key_fallback():
                    logger.warning(
                        "Gemini OAuth rate-limited, falling back to API key for %s",
                        model,
                    )
                    return await sdk_complete(
                        self._client, messages, model, temperature,
                        max_tokens, self.provider_name, kwargs,
                    )
                raise
        return await sdk_complete(
            self._client, messages, model, temperature,
            max_tokens, self.provider_name, kwargs,
        )

    async def health_check(self) -> bool:
        """Check if Gemini API is reachable."""
        try:
            if self._auth_mode == "oauth" and self._cc_client is not None:
                return await cloudcode_health_check(self._cc_client)
            return await sdk_health_check(self._client)
        except Exception as e:
            logger.warning("Gemini health check failed: %s", e)
            return False

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion from Gemini API."""
        self._refresh_credentials()
        if self._auth_mode == "oauth" and self._cc_client is not None:
            try:
                async for event in cloudcode_stream(
                    self._cc_client, messages, model, temperature,
                    max_tokens, self.provider_name, kwargs,
                ):
                    yield event
                return
            except ProviderError as e:
                if e.retriable and self._has_api_key_fallback():
                    logger.warning(
                        "Gemini OAuth rate-limited during stream, falling back to API key for %s",
                        model,
                    )
                    # Fall through to SDK stream below
                else:
                    raise
        async for event in sdk_stream(
            self._client, messages, model, temperature,
            max_tokens, self.provider_name, kwargs,
        ):
            yield event

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None = None,
        max_tokens: int | None = None,
        max_turns: int = 20,
        project_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Run agentic loop with tool execution, yielding (event, session_id) tuples."""
        if self._auth_mode == "oauth" and self._cc_client is not None:
            self._refresh_credentials()
        async for event in tool_loop(
            self._auth_mode, self._cc_client, self._client,
            messages, model, tools, working_dir, max_tokens, max_turns,
            self.provider_name, project_id, kwargs,
        ):
            yield event


__all__ = [
    "GeminiAdapter",
    "GeminiSettings",
    "_resolve_oauth_data",
    "get_gemini_auth_preference",
    "get_gemini_vertex_project",
    "set_gemini_auth_preference",
    "set_gemini_vertex_project",
]
