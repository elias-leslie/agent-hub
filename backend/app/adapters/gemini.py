"""Gemini adapter using Google GenAI SDK."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from google import genai
from google.genai import types
from google.genai.types import HttpOptions

from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderAdapter,
    StreamEvent,
)
from app.adapters.gemini_thinking import get_thinking_level
from app.adapters.gemini_tools import execute_tool_loop
from app.adapters.gemini_utils import (
    build_config as build_gemini_config,
)
from app.adapters.gemini_utils import (
    convert_messages,
    handle_error,
)
from app.adapters.gemini_utils import (
    process_response as process_gemini_response,
)
from app.config import settings

logger = logging.getLogger(__name__)


class GeminiAdapter(ProviderAdapter):
    """Adapter for Gemini models via Google GenAI API."""

    def __init__(
        self,
        api_key: str | None = None,
        before_tool_callback: (Callable[[str, dict[str, Any]], Awaitable[bool]] | None) = None,
        after_tool_callback: (Callable[[str, dict[str, Any], str], Awaitable[None]] | None) = None,
    ):
        """
        Initialize Gemini adapter.

        Args:
            api_key: Google API key. Falls back to settings if not provided.
            before_tool_callback: Async callback before tool execution.
                Called with (tool_name, tool_args), returns True to allow.
            after_tool_callback: Async callback after tool execution.
                Called with (tool_name, tool_input, tool_output).
        """
        self._api_key = api_key or settings.gemini_api_key
        if not self._api_key:
            raise ValueError("Google API key not configured")
        # SDK-level timeout for TRUE idle detection at transport layer (90s based on profiling)
        # Note: HttpOptions timeout is in milliseconds
        self._client = genai.Client(
            api_key=self._api_key,
            http_options=HttpOptions(timeout=90_000),  # 90 seconds in ms
        )
        self._before_tool_callback = before_tool_callback
        self._after_tool_callback = after_tool_callback

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion using Gemini API."""
        return await self._complete_with_retry(messages, model, max_tokens, temperature, **kwargs)

    async def _complete_with_retry(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion using Gemini API with retry logic."""
        from tenacity import (
            retry,
            retry_if_exception,
            stop_after_attempt,
            wait_random_exponential,
        )

        from app.adapters.base import is_retriable_error

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
        system_instruction, contents = convert_messages(messages)

        try:
            # Build config
            config = build_gemini_config(
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                response_format=kwargs.get("response_format"),
                system_instruction=system_instruction,
                tools=kwargs.get("tools"),
                **kwargs,
            )

            # Make API call
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

            return process_gemini_response(response, model, self.provider_name)

        except Exception as e:
            handle_error(e, self.provider_name)

    async def health_check(self) -> bool:
        """Check if Gemini API is reachable."""
        try:
            from app.constants import GEMINI_FLASH

            response = await self._client.aio.models.generate_content(
                model=GEMINI_FLASH,
                contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
                config=types.GenerateContentConfig(max_output_tokens=50),
            )
            return response.text is not None or bool(response.candidates)
        except Exception as e:
            logger.warning(f"Gemini health check failed: {e}")
            return False

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion from Gemini API."""
        system_instruction, contents = convert_messages(messages)

        try:
            # Build config - disable AFC to prevent internal polling loops
            config_params: dict[str, Any] = {
                "temperature": temperature,
                "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
            }
            if max_tokens is not None:
                config_params["max_output_tokens"] = max_tokens

            config = types.GenerateContentConfig(**config_params)

            # Gemini 3 thinking config
            thinking_level = get_thinking_level(model, kwargs.get("thinking_level"))
            if thinking_level:
                config.thinking_config = types.ThinkingConfig(thinking_level=thinking_level)

            if system_instruction:
                config.system_instruction = system_instruction

            # Stream response
            total_content = ""
            async for chunk in await self._client.aio.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            ):
                if chunk.text:
                    total_content += chunk.text
                    yield StreamEvent(type="content", content=chunk.text)

            # Final event with usage
            yield StreamEvent(
                type="done",
                input_tokens=0,
                output_tokens=len(total_content) // 4,
                finish_reason="STOP",
            )

        except Exception as e:
            logger.error(f"Gemini stream error: {e}")
            yield StreamEvent(type="error", error=str(e))

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None = None,
        max_tokens: int = 4096,
        max_turns: int = 20,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Run agentic loop with tool execution.

        Args:
            messages: Conversation messages
            model: Model identifier
            tools: Tool definitions in Gemini format
            working_dir: Working directory for tool execution
            max_tokens: Maximum tokens per response
            max_turns: Maximum agentic turns (default 20)
            **kwargs: Additional parameters

        Yields:
            Tuple of (event_object, session_id) similar to Claude SDK format
        """
        async for event in execute_tool_loop(
            client=self._client,
            messages=messages,
            model=model,
            tools=tools,
            working_dir=working_dir,
            max_tokens=max_tokens,
            max_turns=max_turns,
            provider_name=self.provider_name,
            **kwargs,
        ):
            yield event
