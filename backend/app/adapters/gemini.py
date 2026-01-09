"""Gemini adapter using Google GenAI SDK."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from google import genai
from google.genai import types

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    RateLimitError,
    StreamEvent,
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
        self._client = genai.Client(api_key=self._api_key)
        self._before_tool_callback = before_tool_callback
        self._after_tool_callback = after_tool_callback

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _build_parts(self, content: str | list[dict[str, Any]]) -> list[types.Part]:
        """Build Gemini parts from content.

        Args:
            content: Either a string or list of content blocks (text/image).

        Returns:
            List of Gemini Part objects.
        """
        if isinstance(content, str):
            return [types.Part(text=content)]

        parts: list[types.Part] = []
        for block in content:
            if isinstance(block, str):
                parts.append(types.Part(text=block))
            elif isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "text":
                    parts.append(types.Part(text=block.get("text", "")))
                elif block_type == "image":
                    # Extract image data from source
                    source = block.get("source", {})
                    if source.get("type") == "base64":
                        import base64

                        media_type = source.get("media_type", "image/png")
                        data = source.get("data", "")
                        # Gemini expects raw bytes for inline_data
                        image_bytes = base64.b64decode(data)
                        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=media_type))
        return parts

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion using Gemini API."""
        # Extract system message and build content
        system_instruction: str | None = None
        contents: list[types.Content] = []

        for msg in messages:
            if msg.role == "system":
                # System messages must be strings
                system_instruction = (
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                )
            else:
                # Map roles: user -> user, assistant -> model
                role = "model" if msg.role == "assistant" else "user"
                parts = self._build_parts(msg.content)
                contents.append(types.Content(role=role, parts=parts))

        try:
            # Build config - disable AFC to prevent internal polling loops
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
            if system_instruction:
                config.system_instruction = system_instruction

            # Make API call (google-genai supports both sync and async)
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

            # Extract content
            content = ""
            if response.text:
                content = response.text

            # Extract token counts from usage metadata
            input_tokens = 0
            output_tokens = 0
            if response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count or 0
                output_tokens = response.usage_metadata.candidates_token_count or 0

            # Determine finish reason
            finish_reason = None
            if response.candidates and response.candidates[0].finish_reason:
                finish_reason = str(response.candidates[0].finish_reason)

            return CompletionResult(
                content=content,
                model=model,
                provider=self.provider_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
                raw_response=response,
            )

        except Exception as e:
            error_str = str(e).lower()

            # Check for rate limit errors
            if "429" in str(e) or "rate" in error_str or "quota" in error_str:
                logger.warning(f"Gemini rate limit: {e}")
                raise RateLimitError(self.provider_name) from e

            # Check for auth errors
            if "401" in str(e) or "403" in str(e) or "api key" in error_str:
                logger.error(f"Gemini auth error: {e}")
                raise AuthenticationError(self.provider_name) from e

            # Generic provider error
            logger.error(f"Gemini API error: {e}")
            raise ProviderError(
                str(e),
                provider=self.provider_name,
                retriable="500" in str(e) or "503" in str(e),
            ) from e

    async def health_check(self) -> bool:
        """Check if Gemini API is reachable."""
        try:
            # Use a minimal request to check connectivity
            from app.constants import GEMINI_FLASH

            response = await self._client.aio.models.generate_content(
                model=GEMINI_FLASH,
                contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
                config=types.GenerateContentConfig(max_output_tokens=50),
            )
            # Check for valid response (text or candidates)
            return response.text is not None or bool(response.candidates)
        except Exception as e:
            logger.warning(f"Gemini health check failed: {e}")
            return False

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion from Gemini API."""
        # Extract system message and build content
        system_instruction: str | None = None
        contents: list[types.Content] = []

        for msg in messages:
            if msg.role == "system":
                # System messages must be strings
                system_instruction = (
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                )
            else:
                role = "model" if msg.role == "assistant" else "user"
                parts = self._build_parts(msg.content)
                contents.append(types.Content(role=role, parts=parts))

        try:
            # Build config - disable AFC to prevent internal polling loops
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
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
            input_tokens = 0
            output_tokens = len(total_content) // 4  # Estimate

            yield StreamEvent(
                type="done",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason="STOP",
            )

        except Exception as e:
            logger.error(f"Gemini stream error: {e}")
            yield StreamEvent(type="error", error=str(e))
