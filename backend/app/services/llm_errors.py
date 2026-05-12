"""Provider error types and retry logic."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
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
_DURATION_UNITS: dict[str, float] = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
_RETRY_PATTERNS = [
    r"retry after (\d+\.?\d*)\s*s",
    r"try again in (\d+\.?\d*)\s*s",
    r"reset after (\d+\.?\d*)\s*s",
    r"wait (\d+\.?\d*)\s*s",
    r"Please retry after (\d+)",
]


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

    def __init__(
        self,
        provider: str,
        retry_after: float | None = None,
        quota_details: dict[str, str] | None = None,
    ):
        super().__init__(
            f"Rate limit exceeded for {provider}",
            provider=provider,
            retriable=True,
            status_code=429,
        )
        self.retry_after = retry_after
        self.quota_details = quota_details or {}


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
            retriable=True,
            status_code=503,
        )
        self.consecutive_failures = consecutive_failures
        self.last_error_signature = last_error_signature
        self.cooldown_until = cooldown_until


def parse_duration_string(value: str) -> float | None:
    """Parse a Go-style duration string like '1s', '200ms', '1m0s' into seconds."""
    total = 0.0
    matched_any = False
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)(ms|s|m|h)\b", value):
        matched_any = True
        total += float(match.group(1)) * _DURATION_UNITS[match.group(2)]
    return total if matched_any else None


def extract_retry_after_header(headers: dict[str, str], max_delay: float) -> float | None:
    """Parse Retry-After header value (seconds or HTTP date)."""
    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if not retry_after:
        return None
    try:
        return min(float(retry_after), max_delay)
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(retry_after)
        delay = (target - datetime.now(UTC)).total_seconds()
        return min(max(delay, 0), max_delay)
    except Exception:
        return None


def extract_openai_rate_limit_header(headers: dict[str, str], max_delay: float) -> float | None:
    """Parse OpenAI x-ratelimit-reset-* headers into seconds."""
    for header_name in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        value = headers.get(header_name)
        if value:
            parsed = parse_duration_string(value)
            if parsed is not None:
                return min(parsed, max_delay)
    return None


def extract_from_error_message(error: Exception, max_delay: float) -> float | None:
    """Extract delay from common rate-limit patterns in the error message."""
    error_str = str(error)
    for pattern in _RETRY_PATTERNS:
        match = re.search(pattern, error_str, re.IGNORECASE)
        if match:
            return min(float(match.group(1)), max_delay)
    return None


def extract_from_json_body(body: str, max_delay: float) -> float | None:
    """Extract retryDelay from a Google API JSON error body."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    for detail in data.get("error", {}).get("details", []):
        retry_delay = detail.get("retryDelay")
        if isinstance(retry_delay, str):
            parsed = parse_duration_string(retry_delay)
            if parsed is not None:
                return min(parsed, max_delay)
    return None


def _is_retriable_status_code(code: int) -> bool:
    return code in (429, 503) or code >= 500


def is_retriable_error(exc: BaseException) -> bool:
    """Check if an error is retriable (transient)."""
    if isinstance(exc, ProviderError):
        if exc.retriable:
            return True
        if exc.status_code is not None:
            return _is_retriable_status_code(exc.status_code)

    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status_code, int):
        return _is_retriable_status_code(status_code)

    status_str = getattr(exc, "status", None)
    if isinstance(status_str, str):
        return status_str.upper() in _RETRIABLE_GRPC_STATUSES

    return False


def extract_retry_delay(error: Exception, max_delay: float = 60.0) -> float | None:
    """Extract server-requested retry delay in seconds from error response."""
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
    """Decorator that adds retry logic with exponential backoff."""
    return retry(
        retry=retry_if_exception(is_retriable_error),
        stop=stop_after_attempt(3),
        wait=_wait_with_server_delay,
        reraise=True,
    )(func)
