"""Retry delay extraction helpers for provider error handling."""

import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

_DURATION_UNITS: dict[str, float] = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
_RETRY_PATTERNS = [
    r"retry after (\d+\.?\d*)\s*s",
    r"try again in (\d+\.?\d*)\s*s",
    r"reset after (\d+\.?\d*)\s*s",
    r"wait (\d+\.?\d*)\s*s",
    r"Please retry after (\d+)",
]


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
