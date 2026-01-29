"""OpenAI adapter - PLACEHOLDER.

This adapter exists to provide a clear error message when OpenAI models are requested.
Full implementation will be added when OpenAI integration is prioritized.

Status: NOT IMPLEMENTED
Reason: Claude and Gemini cover current needs. OpenAI planned for future.
"""

from collections.abc import AsyncIterator
from typing import Any

from .base import (
    CompletionResult,
    Message,
    ProviderAdapter,
    StreamEvent,
)


class OpenAIAdapter(ProviderAdapter):
    """Placeholder adapter for OpenAI models.

    All methods raise NotImplementedError with guidance.
    """

    @property
    def provider_name(self) -> str:
        return "openai"

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """Not implemented - OpenAI support planned for future."""
        raise NotImplementedError(
            f"OpenAI model '{model}' is not yet supported. "
            "Current supported providers: claude, gemini. "
            "OpenAI integration planned for future release."
        )

    async def health_check(self) -> bool:
        """Health check - always returns False as not implemented."""
        return False

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Not implemented - OpenAI support planned for future."""
        raise NotImplementedError(
            f"OpenAI model '{model}' streaming is not yet supported. "
            "Current supported providers: claude, gemini. "
            "OpenAI integration planned for future release."
        )
