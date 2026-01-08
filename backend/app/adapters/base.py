"""Base protocol and types for provider adapters."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class StreamEvent:
    """Event from streaming completion."""

    type: Literal["content", "done", "error", "thinking"]
    content: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    error: str | None = None
    # Extended thinking support
    thinking_tokens: int | None = None  # Tokens used for thinking


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
class ToolCallResult:
    """A tool call in a completion response (for programmatic tool calling)."""

    id: str
    name: str
    input: dict[str, Any]
    caller_type: str = "direct"  # "direct" or "code_execution_20250825"
    caller_tool_id: str | None = None  # Set when called from code_execution


@dataclass
class ContainerState:
    """Container state for programmatic tool calling."""

    id: str
    expires_at: str  # ISO timestamp


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
    # Programmatic tool calling fields
    tool_calls: list[ToolCallResult] | None = None
    container: ContainerState | None = None
    # Extended thinking fields
    thinking_content: str | None = None
    thinking_tokens: int | None = None


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

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """
        Stream a completion for the given messages.

        Args:
            messages: Conversation history
            model: Model identifier to use
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            **kwargs: Provider-specific parameters

        Yields:
            StreamEvent with content chunks and metadata

        Raises:
            ProviderError: If the request fails
        """
        # Default implementation: call complete and yield single event
        result = await self.complete(messages, model, max_tokens, temperature, **kwargs)
        yield StreamEvent(type="content", content=result.content)
        yield StreamEvent(
            type="done",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            finish_reason=result.finish_reason,
        )


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
