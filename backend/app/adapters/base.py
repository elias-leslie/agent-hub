"""Base protocol and types for provider adapters."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class StreamEvent:
    """Event from streaming completion."""

    type: Literal["content", "done", "error"]
    content: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    error: str | None = None


@dataclass
class Message:
    """A message in a conversation."""

    role: Literal["user", "assistant", "system"]
    content: str


@dataclass
class CacheMetrics:
    """Cache usage metrics for prompt caching."""

    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate (0.0-1.0)."""
        total = self.cache_creation_input_tokens + self.cache_read_input_tokens
        if total == 0:
            return 0.0
        return self.cache_read_input_tokens / total


@dataclass
class CompletionResult:
    """Result from a completion request."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None = None
    raw_response: Any = None
    cache_metrics: CacheMetrics | None = None


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
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Generate a completion for the given messages.

        Args:
            messages: Conversation history
            model: Model identifier to use
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
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


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(
        self,
        message: str,
        provider: str,
        retriable: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.retriable = retriable
        self.status_code = status_code


class RateLimitError(ProviderError):
    """Provider rate limit exceeded."""

    def __init__(self, provider: str, retry_after: float | None = None):
        super().__init__(
            f"Rate limit exceeded for {provider}",
            provider=provider,
            retriable=True,
            status_code=429,
        )
        self.retry_after = retry_after


class AuthenticationError(ProviderError):
    """Provider authentication failed."""

    def __init__(self, provider: str):
        super().__init__(
            f"Authentication failed for {provider}",
            provider=provider,
            retriable=False,
            status_code=401,
        )
