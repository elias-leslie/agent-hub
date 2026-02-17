"""Base adapter for OpenAI-compatible APIs.

Shared by OpenRouter, OpenAI, xAI, and Zhipu adapters.
"""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    StreamEvent,
    ToolCallResult,
    is_retriable_error,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleAdapter(ProviderAdapter):
    """Base adapter for providers with OpenAI-compatible APIs.

    Subclasses must implement:
    - provider_name (property)
    - _get_base_url()
    - _get_api_key(explicit_key)

    Optionally override:
    - provider_prefix (class attribute) - set to strip "prefix/" from model IDs
    - _resolve_model(model) - override for custom resolution logic
    - _get_default_headers()
    - _get_client_kwargs()
    """

    provider_prefix: str = ""

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize with API key (explicit → CredentialManager → env var)."""
        # Resolution chain: explicit key → DB credential → env var fallback
        if not api_key:
            from app.services.credential_manager import get_credential_manager

            cm = get_credential_manager()
            if cm.is_initialized:
                api_key = cm.get_api_key(self.provider_name)

        resolved_key = self._get_api_key(api_key)
        if not resolved_key:
            raise ValueError(f"{self.provider_name.title()} API key not configured")

        client_kwargs: dict[str, Any] = {
            "api_key": resolved_key,
            "base_url": self._get_base_url(),
        }

        headers = self._get_default_headers()
        if headers:
            client_kwargs["default_headers"] = headers

        client_kwargs.update(self._get_client_kwargs())
        self._client = AsyncOpenAI(**client_kwargs)

    @abstractmethod
    def _get_base_url(self) -> str:
        """Return the provider's API base URL."""
        ...

    @abstractmethod
    def _get_api_key(self, explicit_key: str | None) -> str:
        """Return the API key, preferring explicit_key over settings."""
        ...

    def _resolve_model(self, model: str) -> str:
        """Resolve model alias/ID to the API model ID.

        Default implementation strips the provider_prefix if set.
        Override for custom resolution logic (e.g. OpenRouter aliases).
        """
        prefix = self.provider_prefix
        if prefix and model.startswith(f"{prefix}/"):
            return model[len(prefix) + 1 :]
        return model

    def _get_default_headers(self) -> dict[str, str] | None:
        """Return extra default headers for the client. Override if needed."""
        return None

    def _get_client_kwargs(self) -> dict[str, Any]:
        """Return extra kwargs for AsyncOpenAI constructor. Override if needed."""
        return {}

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion with tenacity retry."""
        from tenacity import (
            retry,
            retry_if_exception,
            stop_after_attempt,
            wait_random_exponential,
        )

        @retry(
            retry=retry_if_exception(is_retriable_error),
            stop=stop_after_attempt(3),
            wait=wait_random_exponential(multiplier=1, min=2, max=30),
            reraise=True,
        )
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
        openai_messages = self._convert_messages(messages)
        model_id = self._resolve_model(model)

        try:
            params: dict[str, Any] = {
                "model": model_id,
                "messages": openai_messages,
                "temperature": temperature,
            }
            if max_tokens:
                params["max_tokens"] = max_tokens

            if kwargs.get("tools"):
                params["tools"] = kwargs["tools"]
            if kwargs.get("tool_choice"):
                params["tool_choice"] = kwargs["tool_choice"]

            response = await self._client.chat.completions.create(**params)

            choice = response.choices[0]
            content = choice.message.content or ""

            tool_calls = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    tool_calls.append(
                        ToolCallResult(
                            id=tc.id,
                            name=tc.function.name,
                            input=args,
                            caller_type="native",
                            original_id=tc.id,
                        )
                    )

            return CompletionResult(
                content=content,
                model=response.model,
                provider=self.provider_name,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                finish_reason=choice.finish_reason,
                raw_response=response,
                tool_calls=tool_calls if tool_calls else None,
            )

        except Exception as e:
            logger.error(f"{self.provider_name} completion error: {e}")
            self._handle_error(e)
            raise  # Unreachable due to _handle_error raising

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
        openai_messages = self._convert_messages(messages)
        model_id = self._resolve_model(model)

        try:
            params: dict[str, Any] = {
                "model": model_id,
                "messages": openai_messages,
                "temperature": temperature,
                "stream": True,
            }
            if max_tokens:
                params["max_tokens"] = max_tokens

            stream = await self._client.chat.completions.create(**params)

            async for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                if delta.content:
                    yield StreamEvent(type="content", content=delta.content)

            yield StreamEvent(type="done")

        except Exception as e:
            logger.error(f"{self.provider_name} stream error: {e}")
            yield StreamEvent(type="error", error=str(e))

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert internal messages to OpenAI format."""
        openai_messages = []
        for msg in messages:
            content = msg.content
            if isinstance(content, list):
                pass

            openai_messages.append({"role": msg.role, "content": content})
        return openai_messages

    def _handle_error(self, error: Exception) -> None:
        """Map exceptions to ProviderError types."""
        msg = str(error)
        if "401" in msg or "Authentication" in msg:
            raise ProviderError(msg, self.provider_name, status_code=401)
        if "429" in msg or "Rate limit" in msg:
            raise ProviderError(msg, self.provider_name, retriable=True, status_code=429)
        raise ProviderError(msg, self.provider_name, retriable=True)
