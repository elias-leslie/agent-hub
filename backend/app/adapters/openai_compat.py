"""Base adapter for OpenAI-compatible APIs.

Shared by OpenRouter, OpenAI, xAI, and Zhipu adapters.
"""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from app.adapters._openai_compat_helpers import (
    build_client_kwargs,
    build_completion_params,
    build_stream_params,
    convert_messages,
    handle_provider_error,
    iterate_stream,
    parse_completion_response,
    resolve_api_key,
)
from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderAdapter,
    StreamEvent,
)

logger = logging.getLogger(__name__)
_EMPTY_FINAL_RESPONSE_MSG = (
    "You have finished tool work but have not produced a final user-facing response. "
    "Write the final response now. "
    "If no changes were needed, say so plainly. "
    "If changes were made, summarize the exact changes and evidence. "
    "Do not call more tools unless a missing fact blocks the response."
)


def _is_auth_error(error: Exception) -> bool:
    """Return True when the provider error looks like authentication."""
    message = str(error).lower()
    return "401" in message or "authentication" in message or "unauthorized" in message


async def _load_credentials_from_db(provider_name: str) -> str | None:
    """Reload credentials from the database and return the provider key."""
    try:
        from app.db import async_session
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        async with async_session() as db:
            await cm.load(db)
        return cm.get_api_key(provider_name)
    except Exception:
        logger.debug("DB credential reload failed for %s", provider_name, exc_info=True)
        return None


def _build_assistant_tool_message(result: CompletionResult) -> dict[str, Any]:
    """Build the assistant message dict with tool_calls for conversation history."""
    return {
        "role": "assistant",
        "content": result.content or None,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.input)},
            }
            for tc in result.tool_calls  # type: ignore[union-attr]
        ],
    }


async def _execute_tool_calls(
    result: CompletionResult,
    openai_messages: list[dict[str, Any]],
    tool_handler: Callable[[str, dict[str, Any]], Awaitable[str]],
) -> AsyncIterator[StreamEvent]:
    """Execute all tool calls from a result, appending messages and yielding events."""
    openai_messages.append(_build_assistant_tool_message(result))
    if result.content:
        yield StreamEvent(type="content", content=result.content)
    for tc in result.tool_calls:  # type: ignore[union-attr]
        yield StreamEvent(type="tool_use", tool_id=tc.id, tool_name=tc.name, tool_input=tc.input)
        tool_result_str = await tool_handler(tc.name, tc.input)
        yield StreamEvent(type="tool_result", tool_id=tc.id, content=tool_result_str)
        openai_messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result_str})


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

    def _set_client_api_key(self, api_key: str) -> None:
        """Update the underlying client with a new API key."""
        self._client.api_key = api_key
        self._last_resolved_key = api_key

    async def _refresh_credentials(self, *, allow_db_reload: bool = False) -> str | None:
        """Re-check CredentialManager for a fresher API key.

        Called before each API call so long-running agentic sessions pick up
        rotated keys without adapter recreation.
        """
        try:
            fresh = resolve_api_key(self.provider_name, None)
            if not fresh and allow_db_reload:
                fresh = await _load_credentials_from_db(self.provider_name)
            if fresh and fresh != self._last_resolved_key:
                self._set_client_api_key(fresh)
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
            return await self._complete_impl(messages, model, max_tokens, temperature, **kwargs)

        return await _do_complete()

    async def _complete_impl(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """Internal implementation of completion."""
        await self._refresh_credentials()
        params = build_completion_params(
            self._resolve_model(model), convert_messages(messages), temperature, max_tokens, kwargs,
        )
        try:
            response = await self._client.chat.completions.create(**params)
            return parse_completion_response(response, self.provider_name)
        except Exception as e:
            result, e = await self._retry_on_auth_error(e, params)
            if result is not None:
                return result
            logger.error(f"{self.provider_name} completion error: {e}")
            handle_provider_error(e, self.provider_name)
            raise  # Unreachable

    async def _retry_on_auth_error(
        self, error: Exception, params: dict[str, Any]
    ) -> tuple[CompletionResult | None, Exception]:
        """If error is auth-related, refresh credentials and retry once.

        Returns ``(result, error)`` where result is set on success, or
        ``(None, error_to_report)`` when retry is skipped or fails.
        """
        if not _is_auth_error(error):
            return None, error
        fresh = await self._refresh_credentials(allow_db_reload=True)
        if not fresh:
            return None, error
        try:
            response = await self._client.chat.completions.create(**params)
            return parse_completion_response(response, self.provider_name), error
        except Exception as retry_error:
            return None, retry_error

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
            logger.error(f"{self.provider_name} stream error: {e}")
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
        kwargs = kwargs.copy()
        openai_messages: list[dict[str, Any]] = convert_messages(messages)
        temperature: float = kwargs.pop("temperature", 1.0)
        max_tokens: int | None = kwargs.pop("max_tokens", None)
        extra_kwargs = {**kwargs, "tools": tools}
        empty_closeout_used = False

        for _turn in range(max_turns):
            await self._refresh_credentials()
            params = build_completion_params(
                self._resolve_model(model), openai_messages, temperature, max_tokens, extra_kwargs,
            )
            try:
                response = await self._client.chat.completions.create(**params)
                result = parse_completion_response(response, self.provider_name)
            except Exception as e:
                logger.error(f"{self.provider_name} complete_with_tools error: {e}")
                yield StreamEvent(type="error", error=str(e))
                return

            if result.tool_calls:
                async for event in _execute_tool_calls(result, openai_messages, tool_handler):
                    yield event
                continue

            # No tool calls — handle empty response or finish
            no_content = not (result.content or "").strip()
            if no_content and not empty_closeout_used and _turn + 1 < max_turns:
                openai_messages.append({"role": "user", "content": _EMPTY_FINAL_RESPONSE_MSG})
                empty_closeout_used = True
                continue
            if result.content:
                yield StreamEvent(type="content", content=result.content)
            yield StreamEvent(
                type="done",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                finish_reason=result.finish_reason,
            )
            return

        yield StreamEvent(type="done", finish_reason="max_turns")

    def complete_with_tool_events(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None,
        permission_config: dict[str, Any] | None,
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
            permission_config,
            max_turns,
            project_id,
            session_id,
            agent_slug=agent_slug,
            tool_catalog=tool_catalog,
        )

