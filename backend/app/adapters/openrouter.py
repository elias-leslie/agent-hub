"""OpenRouter adapter using OpenAI SDK."""

import json
import logging
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
from app.config import settings
from app.constants import MODEL_ALIASES

logger = logging.getLogger(__name__)

# Build OpenRouter alias -> API model ID mapping from the central registry.
# Registry IDs are like "openrouter/x-ai/grok-code-fast-1" but the OpenRouter API
# expects "x-ai/grok-code-fast-1" (no openrouter/ prefix).
_OR_ALIAS_MAP: dict[str, str] = {}
for _alias, _model_id in MODEL_ALIASES.items():
    if _model_id.startswith("openrouter/"):
        _OR_ALIAS_MAP[_alias] = _model_id[len("openrouter/"):]

# Legacy aliases not in the registry
_OR_ALIAS_MAP["or/sonnet"] = "anthropic/claude-3.5-sonnet"
_OR_ALIAS_MAP["or/gpt4o"] = "openai/gpt-4o"


def resolve_openrouter_model(model: str) -> str:
    """Resolve model alias to OpenRouter model ID.

    Handles:
    - openrouter/provider/model -> provider/model (prefix strip)
    - or/alias -> mapped from MODEL_ALIASES registry
    - passthrough for unrecognized models
    """
    # Strip openrouter/ prefix if present
    if model.startswith("openrouter/"):
        return model[len("openrouter/"):]

    # Check alias map (derived from constants.MODEL_ALIASES)
    if model in _OR_ALIAS_MAP:
        return _OR_ALIAS_MAP[model]

    return model


class OpenRouterAdapter(ProviderAdapter):
    """Adapter for OpenRouter models via OpenAI SDK."""

    def __init__(self, api_key: str | None = None):
        """Initialize OpenRouter adapter."""
        self._api_key = api_key or settings.openrouter_api_key
        if not self._api_key:
            raise ValueError("OpenRouter API key not configured")

        self._client = AsyncOpenAI(
            api_key=self._api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://agent-hub.dev",
                "X-Title": "Agent Hub",
            },
        )

    @property
    def provider_name(self) -> str:
        return "openrouter"

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion using OpenRouter API."""
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
        model_id = resolve_openrouter_model(model)

        try:
            params = {
                "model": model_id,
                "messages": openai_messages,
                "temperature": temperature,
            }
            if max_tokens:
                params["max_tokens"] = max_tokens

            # Handle tools if present (native OpenAI format)
            if kwargs.get("tools"):
                params["tools"] = kwargs["tools"]
            if kwargs.get("tool_choice"):
                params["tool_choice"] = kwargs["tool_choice"]

            response = await self._client.chat.completions.create(**params)  # type: ignore[call-overload]

            choice = response.choices[0]
            content = choice.message.content or ""

            # Handle tool calls
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
            logger.error(f"OpenRouter completion error: {e}")
            self._handle_error(e)
            raise  # Should be unreachable due to _handle_error raising

    async def health_check(self) -> bool:
        """Check if OpenRouter API is reachable."""
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
        """Stream completion from OpenRouter API."""
        openai_messages = self._convert_messages(messages)
        model_id = resolve_openrouter_model(model)

        try:
            params = {
                "model": model_id,
                "messages": openai_messages,
                "temperature": temperature,
                "stream": True,
            }
            if max_tokens:
                params["max_tokens"] = max_tokens

            stream = await self._client.chat.completions.create(**params)  # type: ignore[call-overload]

            async for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                if delta.content:
                    yield StreamEvent(type="content", content=delta.content)

            yield StreamEvent(type="done")

        except Exception as e:
            logger.error(f"OpenRouter stream error: {e}")
            yield StreamEvent(type="error", error=str(e))

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert internal messages to OpenAI format."""
        openai_messages = []
        for msg in messages:
            content = msg.content
            # Handle multimodal if needed (OpenRouter follows OpenAI vision format)
            if isinstance(content, list):
                # Convert our block format to OpenAI format if needed
                # For now assume text-only or compatible structure
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
