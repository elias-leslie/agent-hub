"""Gemini adapter using Google GenAI SDK."""

import logging
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
)
from app.config import settings

logger = logging.getLogger(__name__)


class GeminiAdapter(ProviderAdapter):
    """Adapter for Gemini models via Google GenAI API."""

    def __init__(self, api_key: str | None = None):
        """
        Initialize Gemini adapter.

        Args:
            api_key: Google API key. Falls back to settings if not provided.
        """
        self._api_key = api_key or settings.gemini_api_key
        if not self._api_key:
            raise ValueError("Google API key not configured")
        self._client = genai.Client(api_key=self._api_key)

    @property
    def provider_name(self) -> str:
        return "gemini"

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
                system_instruction = msg.content
            else:
                # Map roles: user -> user, assistant -> model
                role = "model" if msg.role == "assistant" else "user"
                contents.append(types.Content(role=role, parts=[types.Part(text=msg.content)]))

        try:
            # Build config
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
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
            response = await self._client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=[types.Content(role="user", parts=[types.Part(text="ping")])],
                config=types.GenerateContentConfig(max_output_tokens=10),
            )
            return response.text is not None
        except Exception as e:
            logger.warning(f"Gemini health check failed: {e}")
            return False
