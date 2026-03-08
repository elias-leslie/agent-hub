"""Gemini adapter using Google GenAI SDK (API key) or CloudCode PA (OAuth).

When the primary auth mode is OAuth and a request hits a rate limit (429),
the adapter automatically falls back to SDK clients (API keys) for that
request. Multiple API keys are tried in order until one succeeds.

Failover chain: OAuth → API key 1 → API key 2 → ... → raise error.
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
from app.adapters.gemini_utils import resolve_api_key, resolve_api_keys
from app.constants import GEMINI_IMAGE, GEMINI_IMAGE_NANO, GEMINI_IMAGE_NANO2

logger = logging.getLogger(__name__)

# Image models must always use SDK (API key) — CloudCode PA returns 404 for them
# because it doesn't support multi-modal output (responseModalities: IMAGE).
_IMAGE_MODELS = frozenset({GEMINI_IMAGE, GEMINI_IMAGE_NANO, GEMINI_IMAGE_NANO2})

# Backward-compat alias (cloudcode_claude_auth imports _resolve_oauth_data)
_resolve_oauth_data = resolve_oauth_data


async def _failover_complete(
    sdk_clients: list[Any],
    client: Any,
    messages: list[Message],
    model: str,
    temperature: float,
    max_tokens: int | None,
    provider_name: str,
    kwargs: dict[str, Any],
) -> CompletionResult:
    """Try each SDK client in order; raise last error if all fail."""
    clients = sdk_clients or ([client] if client is not None else [])
    if not clients:
        raise ProviderError("Gemini API key is not configured", provider=provider_name, retriable=False)

    last_error: ProviderError | None = None
    for i, c in enumerate(clients):
        try:
            result = await sdk_complete(c, messages, model, temperature, max_tokens, provider_name, kwargs)
            if i > 0:
                logger.info("Gemini: API key #%d succeeded after %d failure(s)", i + 1, i)
            return result
        except ProviderError as e:
            last_error = e
            if not e.retriable:
                raise
            logger.warning("Gemini API key #%d rate-limited for %s, trying next key", i + 1, model)

    raise last_error  # type: ignore[misc]


async def _failover_stream(
    sdk_clients: list[Any],
    client: Any,
    messages: Any,
    model: str,
    temperature: float,
    max_tokens: int | None,
    provider_name: str,
    kwargs: dict[str, Any],
) -> AsyncIterator[StreamEvent]:
    """Try SDK stream across keys; fail over on retryable pre-content errors."""
    from app.adapters._gemini_cloudcode_ops import (
        _is_retryable_error,  # avoid circular at module level
    )

    clients = sdk_clients or ([client] if client is not None else [])
    if not clients:
        raise ProviderError("Gemini API key is not configured", provider=provider_name, retriable=False)

    for i, c in enumerate(clients):
        emitted_non_error = False
        async for event in sdk_stream(c, messages, model, temperature, max_tokens, provider_name, kwargs):
            if event.type != "error":
                emitted_non_error = True
                yield event
                continue

            can_fail_over = (
                not emitted_non_error
                and i < len(clients) - 1
                and bool(event.error)
                and _is_retryable_error(event.error or "")
            )
            if can_fail_over:
                logger.warning("Gemini API key #%d stream failed (%s), trying next key", i + 1, event.error)
                break
            yield event
            return
        else:
            return

    yield StreamEvent(type="error", error="Gemini stream retries exhausted across API keys")


class GeminiAdapter(ProviderAdapter):
    """Adapter for Gemini models.

    - API key / ADC mode: Uses the Google GenAI SDK (``genai.Client``).
    - OAuth mode: Uses raw HTTP to ``cloudcode-pa.googleapis.com`` via
      :class:`CloudCodeClient` — the same endpoint the Gemini CLI uses,
      which routes through a consumer subscription (zero per-token cost).

    Supports multiple API keys for failover on rate limits.
    """

    def __init__(
        self,
        api_key: str | None = None,
        after_tool_callback: (
            Callable[[str, dict[str, Any], str, int | None], Awaitable[None]] | None
        ) = None,
    ):
        resolved_key = resolve_api_key(api_key)
        oauth_data = resolve_oauth_data()
        self._auth_mode, self._client, self._cc_client = pick_auth_mode(
            resolved_key, oauth_data, get_gemini_auth_preference(),
        )
        self._explicit_api_key = api_key
        self._oauth_project = oauth_data.get("project_id") if oauth_data else None

        # Build list of SDK clients for all available API keys (for failover).
        all_keys = resolve_api_keys()
        self._sdk_clients: list[Any] = []
        self._api_keys: list[str] = []
        for k in all_keys:
            self._sdk_clients.append(make_sdk_client(k))
            self._api_keys.append(k)

        # If we have an explicit key not in the list, add it too
        if resolved_key and resolved_key not in self._api_keys:
            self._sdk_clients.insert(0, make_sdk_client(resolved_key))
            self._api_keys.insert(0, resolved_key)

        # Ensure backward compat: self._client is the first SDK client
        if not self._client and self._sdk_clients:
            self._client = self._sdk_clients[0]

        # Keep an SDK client ready for API-key fallback when OAuth is rate-limited.
        if self._auth_mode == "oauth" and self._sdk_clients:
            if self._client is None:
                self._client = self._sdk_clients[0]
            logger.info(
                "Gemini adapter: OAuth primary with %d API-key fallback(s) available",
                len(self._sdk_clients),
            )

        logger.info(
            "Gemini adapter initialized with %s auth (preference=%s, api_keys=%d)",
            self._auth_mode, get_gemini_auth_preference(), len(self._sdk_clients),
        )
        self._after_tool_callback = after_tool_callback

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _refresh_credentials(self) -> None:
        """Re-check CredentialManager for rotated credentials."""
        try:
            if self._auth_mode == "oauth":
                oauth_data = resolve_oauth_data()
                if oauth_data and oauth_data.get("access_token") and oauth_data.get("project_id"):
                    if self._cc_client is not None:
                        self._cc_client.access_token = oauth_data["access_token"]
                        self._cc_client.project_id = oauth_data["project_id"]
                        if oauth_data.get("refresh_token"):
                            self._cc_client.refresh_token = oauth_data["refresh_token"]
                        if oauth_data.get("expires_at"):
                            self._cc_client.expires_at = oauth_data["expires_at"]
                    else:
                        self._cc_client = make_cloudcode_client(oauth_data)

            # Refresh SDK/API-key clients for both modes (fallback keys for OAuth).
            fresh_keys = resolve_api_keys()
            if not fresh_keys:
                fallback = self._explicit_api_key or resolve_api_key(None)
                if fallback:
                    fresh_keys = [fallback]
            if fresh_keys != self._api_keys:
                self._sdk_clients = [make_sdk_client(k) for k in fresh_keys]
                self._api_keys = fresh_keys
                self._client = self._sdk_clients[0] if self._sdk_clients else None
                logger.debug("Gemini: %d API key(s) refreshed from cache", len(fresh_keys))
        except Exception:
            pass

    def _refresh_api_key(self) -> None:
        """Refresh API key clients from CredentialManager."""
        self._refresh_credentials()

    def _has_api_key_fallback(self) -> bool:
        """Return True when OAuth is primary and API-key fallback clients exist."""
        return self._auth_mode == "oauth" and bool(self._sdk_clients)

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
        # Image models don't work on CloudCode — always use SDK (API key).
        if model in _IMAGE_MODELS:
            logger.info("Image model %s: bypassing CloudCode, using SDK", model)
            return await _failover_complete(
                self._sdk_clients, self._client, messages, model, temperature, max_tokens,
                self.provider_name, kwargs,
            )
        if self._auth_mode == "oauth" and self._cc_client is not None:
            try:
                return await cloudcode_complete(
                    self._cc_client, messages, model, temperature,
                    max_tokens, self.provider_name, kwargs,
                )
            except ProviderError as e:
                if e.retriable and self._sdk_clients:
                    logger.warning(
                        "Gemini OAuth rate-limited, falling back to API keys for %s", model,
                    )
                    return await _failover_complete(
                        self._sdk_clients, self._client, messages, model, temperature, max_tokens,
                        self.provider_name, kwargs,
                    )
                raise
        return await _failover_complete(
            self._sdk_clients, self._client, messages, model, temperature, max_tokens,
            self.provider_name, kwargs,
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
        # Image models don't work on CloudCode — always use SDK (API key).
        if model in _IMAGE_MODELS:
            logger.info("Image model %s: bypassing CloudCode stream, using SDK", model)
            async for event in _failover_stream(
                self._sdk_clients, self._client, messages, model, temperature, max_tokens,
                self.provider_name, kwargs,
            ):
                yield event
            return
        if self._auth_mode == "oauth" and self._cc_client is not None:
            try:
                async for event in cloudcode_stream(
                    self._cc_client, messages, model, temperature,
                    max_tokens, self.provider_name, kwargs,
                ):
                    yield event
                return
            except ProviderError as e:
                if not (e.retriable and self._sdk_clients):
                    raise
                logger.warning(
                    "Gemini OAuth rate-limited during stream, falling back to API keys for %s",
                    model,
                )
        # SDK stream — try across all available clients
        async for event in _failover_stream(
            self._sdk_clients, self._client, messages, model, temperature, max_tokens,
            self.provider_name, kwargs,
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
