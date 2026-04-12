"""Base adapter for OpenAI-compatible APIs.

Shared by OpenRouter, OpenAI, xAI, and Zhipu adapters.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from app.adapters._openai_compat_helpers import (
    build_client_kwargs,
    build_completion_params,
    build_stream_params,
    complete_once,
    convert_messages,
    iterate_stream,
    load_credentials_from_db,
    resolve_api_key,
)
from app.adapters._openai_tool_loop import run_tool_loop
from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderAdapter,
    StreamEvent,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleAdapter(ProviderAdapter):
    """Base adapter for providers with OpenAI-compatible APIs.

    Subclasses must implement: provider_name, _get_base_url(), _get_api_key().
    Optionally override: provider_prefix, _resolve_model(), _get_default_headers(),
    _get_client_kwargs().
    """

    provider_prefix: str = ""

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize with API key (explicit → CredentialManager → env var)."""
        candidate = resolve_api_key(self.provider_name, api_key)
        resolved_key = self._get_api_key(candidate)
        if not resolved_key:
            raise ValueError(f"{self.provider_name.title()} API key not configured")
        kwargs = build_client_kwargs(
            resolved_key, self._get_base_url(), self._get_default_headers(), self._get_client_kwargs()
        )
        self._client = AsyncOpenAI(**kwargs)
        self._last_resolved_key = resolved_key

    @abstractmethod
    def _get_base_url(self) -> str: ...

    @abstractmethod
    def _get_api_key(self, explicit_key: str | None) -> str: ...

    def _resolve_model(self, model: str) -> str:
        """Strip provider_prefix from model ID if present."""
        prefix = self.provider_prefix
        if prefix and model.startswith(f"{prefix}/"):
            return model[len(prefix) + 1 :]
        return model

    def _get_default_headers(self) -> dict[str, str] | None:
        return None

    def _get_client_kwargs(self) -> dict[str, Any]:
        return {}

    async def _refresh_credentials(self, *, allow_db_reload: bool = False) -> str | None:
        """Re-check CredentialManager; updates client key if rotated."""
        try:
            fresh = resolve_api_key(self.provider_name, None)
            if not fresh and allow_db_reload:
                fresh = await load_credentials_from_db(self.provider_name)
            if fresh and fresh != self._last_resolved_key:
                self._client.api_key = fresh
                self._last_resolved_key = fresh
                logger.debug("%s: credential refreshed from cache", self.provider_name)
            return fresh
        except Exception:
            logger.debug("%s: credential refresh failed, keeping existing key", self.provider_name, exc_info=True)
            return None

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion with retry logic."""
        from app.adapters.errors import with_retry

        @with_retry
        async def _do_complete() -> CompletionResult:
            await self._refresh_credentials()
            params = build_completion_params(
                self._resolve_model(model), convert_messages(messages), temperature, max_tokens, kwargs,
            )
            return await complete_once(self._client, self.provider_name, params, self._refresh_credentials)

        return await _do_complete()

    async def health_check(self) -> bool:
        """Check if the provider API is reachable."""
        try:
            await self._client.models.list()
            return True
        except Exception:
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
        """Stream completion from the provider API."""
        await self._refresh_credentials()
        params = build_stream_params(
            self._resolve_model(model), convert_messages(messages), temperature, max_tokens, kwargs
        )
        try:
            raw_stream = await self._client.chat.completions.create(**params)
            async for event in iterate_stream(raw_stream):
                yield event
        except Exception as e:
            logger.error("%s stream error: %s", self.provider_name, e)
            yield StreamEvent(type="error", error=str(e))

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        tool_handler: Callable[[str, dict[str, Any]], Awaitable[str]],
        max_turns: int = 20,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Run an agentic tool-calling loop over the OpenAI-compatible API."""
        kw = kwargs.copy()
        temperature: float = kw.pop("temperature", 1.0)
        max_tokens: int | None = kw.pop("max_tokens", None)
        async for event in run_tool_loop(
            self._client, self.provider_name, self._resolve_model(model),
            messages, tools, tool_handler, self._refresh_credentials,
            max_turns=max_turns, temperature=temperature, max_tokens=max_tokens, **kw,
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
    ) -> AsyncIterator[tuple[Any, str]]:
        """Return canonical ToolEvents for the shared tool execution pipeline."""
        from app.adapters.openai_tool_events import adapt_openai_stream

        return adapt_openai_stream(
            self,
            messages,
            model,
            tools,
            working_dir,
            max_turns,
            project_id,
            session_id,
            agent_slug=agent_slug,
            tool_catalog=tool_catalog,
        )
