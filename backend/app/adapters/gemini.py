"""Gemini adapter using the Google GenAI SDK with API-key failover."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.adapters.base import CompletionResult, Message, ProviderAdapter, StreamEvent
from app.adapters.gemini_adapter_ops import (
    sdk_complete_with_failover,
    sdk_health_check,
    tool_loop,
)
from app.adapters.gemini_adapter_settings import (
    make_sdk_client,
)
from app.adapters.gemini_adapter_stream import sdk_stream_with_failover
from app.adapters.gemini_utils import resolve_api_key, resolve_api_keys
from app.constants.agent_limits import DEFAULT_AGENTIC_MAX_TURNS

logger = logging.getLogger(__name__)


class GeminiAdapter(ProviderAdapter):
    """Adapter for Gemini models.

    Uses the public Google GenAI SDK with one or more API keys loaded from the
    credential manager. Multiple API keys are tried in order on retryable
    failures so a secondary key can pick up after quota/rate-limit events.
    """

    def __init__(
        self,
        api_key: str | None = None,
        after_tool_callback: (
            Callable[[str, dict[str, Any], str, int | None], Awaitable[None]] | None
        ) = None,
    ):
        resolved_key = resolve_api_key(api_key)
        self._explicit_api_key = api_key

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

        self._client = self._sdk_clients[0] if self._sdk_clients else None

        logger.info(
            "Gemini adapter initialized with API-key mode (api_keys=%d)",
            len(self._sdk_clients),
        )
        self._after_tool_callback = after_tool_callback

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _refresh_credentials(self) -> None:
        """Re-check CredentialManager for rotated Gemini API keys."""
        try:
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
            logger.debug("Gemini credential refresh failed", exc_info=True)

    def _refresh_api_key(self) -> None:
        """Refresh API key clients from CredentialManager."""
        self._refresh_credentials()

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
        return await sdk_complete_with_failover(
            self._sdk_clients, self._client, messages, model, temperature, max_tokens,
            self.provider_name, kwargs,
        )

    async def health_check(self) -> bool:
        """Check if Gemini API is reachable."""
        try:
            if self._client is None:
                return False
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
        async for event in sdk_stream_with_failover(
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
        max_turns: int = DEFAULT_AGENTIC_MAX_TURNS,
        project_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Run agentic loop with tool execution, yielding (event, session_id) tuples."""
        self._refresh_credentials()
        async for event in tool_loop(
            self._sdk_clients,
            messages,
            model,
            tools,
            working_dir,
            max_tokens,
            max_turns,
            self.provider_name,
            project_id=project_id,
            **kwargs,
        ):
            yield event

    def complete_with_tool_events(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None,
        max_turns: int,
        project_id: str | None,
        session_id: str,
        agent_slug: str | None,
        tool_catalog: list[dict[str, Any]] | None,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Return canonical ToolEvents for the shared tool execution pipeline."""
        del session_id  # Gemini generates its own tool-loop session ids today.
        return self.complete_with_tools(
            messages=messages,
            model=model,
            tools=tools,
            working_dir=working_dir,
            max_turns=max_turns,
            project_id=project_id,
            agent_slug=agent_slug,
            tool_catalog=tool_catalog,
        )


__all__ = [
    "GeminiAdapter",
]
