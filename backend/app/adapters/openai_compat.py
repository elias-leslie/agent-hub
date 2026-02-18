"""Base adapter for OpenAI-compatible APIs.

Shared by OpenRouter, OpenAI, xAI, and Zhipu adapters.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import AsyncIterator
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

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
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
        params = build_completion_params(
            self._resolve_model(model), convert_messages(messages), temperature, max_tokens, kwargs,
        )
        try:
            response = await self._client.chat.completions.create(**params)
            return parse_completion_response(response, self.provider_name)
        except Exception as e:
            logger.error(f"{self.provider_name} completion error: {e}")
            handle_provider_error(e, self.provider_name)
            raise  # Unreachable

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
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion from the provider API."""
        params = build_stream_params(
            self._resolve_model(model), convert_messages(messages), temperature, max_tokens
        )
        try:
            raw_stream = await self._client.chat.completions.create(**params)
            async for event in iterate_stream(raw_stream):
                yield event
        except Exception as e:
            logger.error(f"{self.provider_name} stream error: {e}")
            yield StreamEvent(type="error", error=str(e))
