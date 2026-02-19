"""Provider error types and retry logic."""

import json
import re
from collections.abc import Callable
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

_F = TypeVar("_F", bound=Callable[..., Any])


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
    # Prefer integer code attributes; google.genai.errors.APIError has .code (int)
    # and .status (str like "UNAVAILABLE") — comparing str >= 500 causes TypeError
    status_code = (
        getattr(exc, "status_code", None)
        or getattr(exc, "code", None)
    )
    if isinstance(status_code, int):
        return status_code == 429 or status_code == 503 or status_code >= 500

    # Fallback: check string status values (e.g., Google API gRPC status strings)
    status_str = getattr(exc, "status", None)
    if isinstance(status_str, str):
        retriable_statuses = {"UNAVAILABLE", "RESOURCE_EXHAUSTED", "INTERNAL", "DEADLINE_EXCEEDED"}
        return status_str.upper() in retriable_statuses

    return False


def _parse_duration_string(value: str) -> float | None:
    """Parse a Go-style duration string like '1s', '200ms', '1m0s' into seconds."""
    total = 0.0
    matched_any = False
    for match in re.finditer(r"(\d+(?:\.\d+)?)(ms|s|m|h)", value):
        matched_any = True
        num = float(match.group(1))
        unit = match.group(2)
        if unit == "ms":
            total += num / 1000
        elif unit == "s":
            total += num
        elif unit == "m":
            total += num * 60
        elif unit == "h":
            total += num * 3600
    return total if matched_any else None


def extract_retry_delay(error: Exception, max_delay: float = 60.0) -> float | None:
    """Extract server-requested retry delay in seconds from error response.

    Parses Retry-After headers, rate limit error bodies, and provider-specific
    delay hints. Returns None if no delay found (fall back to default backoff).
    Caps at max_delay to prevent servers from stalling indefinitely.
    """
    # Check RateLimitError.retry_after from our own exception type
    if isinstance(error, RateLimitError) and error.retry_after is not None:
        return min(error.retry_after, max_delay)

    # 1. Retry-After header
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or {}

    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after:
        try:
            delay = float(retry_after)
            return min(delay, max_delay)
        except ValueError:
            pass
        # Try HTTP date format
        try:
            from datetime import datetime

            target = parsedate_to_datetime(retry_after)
            delay = (target - datetime.now(UTC)).total_seconds()
            return min(max(delay, 0), max_delay)
        except Exception:
            pass

    # 2. OpenAI rate limit reset headers
    for header_name in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        value = headers.get(header_name)
        if value:
            parsed = _parse_duration_string(value)
            if parsed is not None:
                return min(parsed, max_delay)

    # 3. Error message patterns
    error_str = str(error)
    patterns = [
        r"retry after (\d+\.?\d*)\s*s",
        r"try again in (\d+\.?\d*)\s*s",
        r"wait (\d+\.?\d*)\s*s",
        r"Please retry after (\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, error_str, re.IGNORECASE)
        if match:
            delay = float(match.group(1))
            return min(delay, max_delay)

    # 4. Google API retryDelay in JSON body
    body = getattr(response, "text", None) or getattr(response, "body", None)
    if body and isinstance(body, str):
        try:
            data = json.loads(body)
            details = data.get("error", {}).get("details", [])
            for detail in details:
                retry_delay = detail.get("retryDelay")
                if retry_delay and isinstance(retry_delay, str):
                    parsed = _parse_duration_string(retry_delay)
                    if parsed is not None:
                        return min(parsed, max_delay)
        except (json.JSONDecodeError, AttributeError):
            pass

    return None


def _wait_with_server_delay(retry_state: RetryCallState) -> float:
    """Custom tenacity wait callback that prefers server-requested delays."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc is not None:
        delay = extract_retry_delay(exc)
        if delay is not None:
            return delay
    # Fall back to exponential backoff (2-30s with jitter)
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
