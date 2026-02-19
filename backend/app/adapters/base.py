"""Base protocol and types for provider adapters."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

# Re-export core types
from .errors import (
    AuthenticationError,
    CircuitBreakerError,
    ProviderError,
    RateLimitError,
    is_retriable_error,
    with_retry,
)
from .types import (
    CacheMetrics,
    CompletionResult,
    ContainerState,
    Message,
    StreamEvent,
    ToolCallResult,
)
from .utils import ToolCallIdNormalizer

__all__ = [
    "AuthenticationError",
    "CacheMetrics",
    "CircuitBreakerError",
    "CompletionResult",
    "ContainerState",
    "Message",
    "ProviderAdapter",
    "ProviderError",
    "RateLimitError",
    "StreamEvent",
    "ToolCallIdNormalizer",
    "ToolCallResult",
    "is_retriable_error",
    "with_retry",
]


class ProviderAdapter(ABC):
    """Protocol for AI provider adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'claude', 'gemini')."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Generate a completion for the given messages.

        Args:
            messages: Conversation history
            model: Model identifier to use
            max_tokens: Maximum tokens in response (optional - models use defaults if None)
            temperature: Sampling temperature
            cache_retention: Prompt caching hint — "none" (default), "short", or "long".
                Currently only actionable for Anthropic direct API adapters; other
                providers accept the parameter but treat it as a no-op.
            **kwargs: Provider-specific parameters

        Returns:
            CompletionResult with generated content and metadata

        Raises:
            ProviderError: If the request fails
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is available and working."""
        ...

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """
        Stream a completion for the given messages.

        Args:
            messages: Conversation history
            model: Model identifier to use
            max_tokens: Maximum tokens in response (optional - models use defaults if None)
            temperature: Sampling temperature
            cache_retention: Prompt caching hint — "none" (default), "short", or "long".
                Currently only actionable for Anthropic direct API adapters; other
                providers accept the parameter but treat it as a no-op.
            **kwargs: Provider-specific parameters

        Yields:
            StreamEvent with content chunks and metadata

        Raises:
            ProviderError: If the request fails
        """
        # Default implementation: call complete and yield single event
        result = await self.complete(messages, model, max_tokens, temperature, cache_retention=cache_retention, **kwargs)
        yield StreamEvent(type="content", content=result.content)
        yield StreamEvent(
            type="done",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            finish_reason=result.finish_reason,
        )
