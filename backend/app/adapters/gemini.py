"""Gemini adapter using Google GenAI SDK."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from google import genai
from google.genai import types
from google.genai.types import HttpOptions

from app.adapters.base import CompletionResult, Message, ProviderAdapter, StreamEvent
from app.adapters.gemini_thinking import get_thinking_level
from app.adapters.gemini_tools import execute_tool_loop
from app.adapters.gemini_utils import (
    build_stream_config,
    convert_messages,
    do_complete_call,
    extract_chunk_tool_events,
    resolve_api_key,
)
from app.config import settings

logger = logging.getLogger(__name__)


class GeminiAdapter(ProviderAdapter):
    """Adapter for Gemini models via Google GenAI API."""

    def __init__(
        self,
        api_key: str | None = None,
        before_tool_callback: (Callable[[str, dict[str, Any]], Awaitable[bool]] | None) = None,
        after_tool_callback: (Callable[[str, dict[str, Any], str, int | None], Awaitable[None]] | None) = None,
    ):
        """Initialize Gemini adapter. Falls back to DB credential then env var if api_key is None."""
        self._api_key = resolve_api_key(api_key) or settings.gemini_api_key
        if not self._api_key:
            raise ValueError("Google API key not configured")
        # SDK timeout is in milliseconds; 300_000 ms = 300 s for agentic calls
        self._client = genai.Client(
            api_key=self._api_key,
            http_options=HttpOptions(timeout=300_000),
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
        from app.adapters.errors import with_retry

        @with_retry
        async def _do_complete() -> CompletionResult:
            return await do_complete_call(
                self._client, messages, model, temperature, max_tokens, self.provider_name, kwargs,
            )

        return await _do_complete()

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
            config = build_stream_config(
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                system_instruction=system_instruction,
                tools_defs=kwargs.get("tools"),
                thinking_level=get_thinking_level(model, kwargs.get("thinking_level")),
            )
            total_content = ""
            async for chunk in await self._client.aio.models.generate_content_stream(
                model=model, contents=contents, config=config,
            ):
                if chunk.text:
                    total_content += chunk.text
                    yield StreamEvent(type="content", content=chunk.text)
                for event in extract_chunk_tool_events(chunk):
                    yield event

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
        max_tokens: int | None = None,
        max_turns: int = 20,
        project_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Run agentic loop with tool execution, yielding (event, session_id) tuples."""
        async for event in execute_tool_loop(
            client=self._client,
            messages=messages,
            model=model,
            tools=tools,
            working_dir=working_dir,
            max_tokens=max_tokens,
            max_turns=max_turns,
            provider_name=self.provider_name,
            project_id=project_id,
            **kwargs,
        ):
            yield event
