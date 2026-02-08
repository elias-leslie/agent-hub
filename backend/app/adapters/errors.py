"""Provider error types and retry logic."""

from typing import Any

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
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
        return bool(status_code == 429 or status_code == 503 or status_code >= 500)

    return False


def with_retry(func: Any) -> Any:
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
    return retry(
        retry=retry_if_exception(is_retriable_error),
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )(func)
