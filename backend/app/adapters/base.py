"""Base protocol and types for provider adapters."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

# Default output limit - matches app.constants.DEFAULT_OUTPUT_LIMIT
# Using literal here to avoid circular import with constants.py
_DEFAULT_MAX_TOKENS = 8192


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
    """A message in a conversation.

    Content can be:
    - str: Simple text content
    - list[dict]: Content blocks for vision (text + image)

    Image block format:
    {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "<base64-encoded-data>"
        }
    }
    """

    role: Literal["user", "assistant", "system"]
    content: str | list[dict[str, Any]]

    def has_images(self) -> bool:
        """Check if this message contains image content."""
        if isinstance(self.content, str):
            return False
        return any(
            isinstance(block, dict) and block.get("type") == "image" for block in self.content
        )


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
        max_tokens: int = _DEFAULT_MAX_TOKENS,
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
        max_tokens: int = _DEFAULT_MAX_TOKENS,
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


class CircuitBreakerError(ProviderError):
    """Circuit breaker opened due to repeated failures (thrashing)."""

    def __init__(
        self,
        provider: str,
        consecutive_failures: int,
        last_error_signature: str,
        cooldown_until: float | None = None,
    ):
        super().__init__(
            f"Circuit breaker open for {provider}: {consecutive_failures} consecutive failures",
            provider=provider,
            retriable=True,  # Retriable after cooldown
            status_code=503,
        )
        self.consecutive_failures = consecutive_failures
        self.last_error_signature = last_error_signature
        self.cooldown_until = cooldown_until


# Retry logic for transient errors
def is_retriable_error(exc: BaseException) -> bool:
    """Check if an error is retriable (transient).

    Retriable errors include:
    - HTTP 429 (rate limit)
    - HTTP 503 (service unavailable)
    - HTTP 5xx (server errors)
    - ProviderError with retriable=True

    Args:
        exc: The exception to check

    Returns:
        True if the error is retriable, False otherwise
    """
    # Check ProviderError types
    if isinstance(exc, ProviderError):
        if exc.retriable:
            return True
        # Also retry on specific status codes
        if exc.status_code:
            return exc.status_code == 429 or exc.status_code == 503 or exc.status_code >= 500

    # Check for HTTP-like status codes in other exceptions
    status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status_code:
        return status_code == 429 or status_code == 503 or status_code >= 500

    return False


def with_retry(func):
    """Decorator that adds retry logic with exponential backoff.

    Uses tenacity for retry handling:
    - Stops after 3 attempts
    - Exponential backoff: 2-30 seconds with jitter
    - Only retries on transient errors (503, 429, 5xx)

    Example:
        @with_retry
        async def make_api_call():
            ...
    """
    from tenacity import (
        retry,
        retry_if_exception,
        stop_after_attempt,
        wait_random_exponential,
    )

    return retry(
        retry=retry_if_exception(is_retriable_error),
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )(func)
