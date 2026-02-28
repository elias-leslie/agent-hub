"""Provider error types and retry logic."""

from collections.abc import Callable
from typing import TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from app.adapters._errors_retry_delay import (
    extract_from_error_message,
    extract_from_json_body,
    extract_openai_rate_limit_header,
    extract_retry_after_header,
)
from app.adapters._errors_types import (
    AuthenticationError,
    CircuitBreakerError,
    ProviderError,
    RateLimitError,
)

__all__ = [
    "AuthenticationError",
    "CircuitBreakerError",
    "ProviderError",
    "RateLimitError",
    "extract_retry_delay",
    "is_retriable_error",
    "with_retry",
]

_F = TypeVar("_F", bound=Callable[..., object])
_RETRIABLE_GRPC_STATUSES = {"UNAVAILABLE", "RESOURCE_EXHAUSTED", "INTERNAL", "DEADLINE_EXCEEDED"}


def _is_retriable_status_code(code: int) -> bool:
    return code in (429, 503) or code >= 500


def is_retriable_error(exc: BaseException) -> bool:
    """Check if an error is retriable (transient).

    Retriable errors include HTTP 429, 503, 5xx, or ProviderError with retriable=True.
    """
    if isinstance(exc, ProviderError):
        if exc.retriable:
            return True
        if exc.status_code is not None:
            return _is_retriable_status_code(exc.status_code)

    # Prefer integer code; google.genai.errors.APIError has .code (int)
    # and .status (str) — comparing str >= 500 causes TypeError
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status_code, int):
        return _is_retriable_status_code(status_code)

    status_str = getattr(exc, "status", None)
    if isinstance(status_str, str):
        return status_str.upper() in _RETRIABLE_GRPC_STATUSES

    return False


def extract_retry_delay(error: Exception, max_delay: float = 60.0) -> float | None:
    """Extract server-requested retry delay in seconds from error response.

    Parses Retry-After headers, rate limit error bodies, and provider-specific
    delay hints. Returns None if no delay found (fall back to default backoff).
    Caps at max_delay to prevent servers from stalling indefinitely.
    """
    if isinstance(error, RateLimitError) and error.retry_after is not None:
        return min(error.retry_after, max_delay)

    response = getattr(error, "response", None)
    headers: dict[str, str] = getattr(response, "headers", None) or {}

    for extractor in (extract_retry_after_header, extract_openai_rate_limit_header):
        delay = extractor(headers, max_delay)
        if delay is not None:
            return delay

    delay = extract_from_error_message(error, max_delay)
    if delay is not None:
        return delay

    body: str | None = getattr(response, "text", None) or getattr(response, "body", None)
    if body and isinstance(body, str):
        return extract_from_json_body(body, max_delay)

    return None


def _wait_with_server_delay(retry_state: RetryCallState) -> float:
    """Custom tenacity wait callback that prefers server-requested delays."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc is not None:
        delay = extract_retry_delay(exc)
        if delay is not None:
            return delay
    return wait_random_exponential(multiplier=1, min=2, max=30)(retry_state)


def with_retry(func: _F) -> _F:
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
        wait=_wait_with_server_delay,
        reraise=True,
    )(func)
