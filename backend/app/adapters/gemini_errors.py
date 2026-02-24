"""Error handling for Gemini adapter."""

import json
import logging
import re
from typing import NoReturn

logger = logging.getLogger(__name__)


def extract_gemini_quota_details(e: Exception) -> dict[str, str]:
    """Extract quota metadata from a Gemini API error.

    Parses the error's `details` attribute (google.genai.errors.APIError)
    or the response JSON body for structured quota information.

    Returns dict with keys like: quota_metric, quota_limit, consumer, status, retry_delay.
    Empty dict if nothing extractable.
    """
    info: dict[str, str] = {}

    # google.genai.errors.APIError stores full response JSON in .details
    details_obj = getattr(e, "details", None)
    if details_obj and isinstance(details_obj, dict):
        error_block = details_obj.get("error", details_obj)
        info["status"] = str(error_block.get("status", ""))
        info["message"] = str(error_block.get("message", ""))[:200]
        for detail in error_block.get("details", []):
            metadata = detail.get("metadata", {})
            if "quota_metric" in metadata:
                info["quota_metric"] = metadata["quota_metric"]
            if "quota_limit_value" in metadata:
                info["quota_limit"] = metadata["quota_limit_value"]
            if "consumer" in metadata:
                info["consumer"] = metadata["consumer"]
            if detail.get("retryDelay"):
                info["retry_delay"] = detail["retryDelay"]

    # Also try httpx response body (CloudCode / raw HTTP errors)
    response = getattr(e, "response", None)
    if response and not info.get("quota_metric"):
        body = getattr(response, "text", None)
        if body and isinstance(body, str):
            try:
                data = json.loads(body)
                error_block = data.get("error", data)
                if not info.get("status"):
                    info["status"] = str(error_block.get("status", ""))
                if not info.get("message"):
                    info["message"] = str(error_block.get("message", ""))[:200]
                for detail in error_block.get("details", []):
                    metadata = detail.get("metadata", {})
                    if "quota_metric" in metadata:
                        info["quota_metric"] = metadata["quota_metric"]
                    if "quota_limit_value" in metadata:
                        info["quota_limit"] = metadata["quota_limit_value"]
                    if "consumer" in metadata:
                        info["consumer"] = metadata["consumer"]
                    if detail.get("retryDelay"):
                        info["retry_delay"] = detail["retryDelay"]
            except (json.JSONDecodeError, AttributeError):
                pass

    # Clean out empty strings
    return {k: v for k, v in info.items() if v}


def _log_rate_limit(e: Exception, provider_name: str, quota: dict[str, str]) -> None:
    """Log rate limit with structured quota details."""
    metric = quota.get("quota_metric", "unknown")
    limit = quota.get("quota_limit", "?")
    consumer = quota.get("consumer", "unknown")
    retry_delay = quota.get("retry_delay", "")
    status = quota.get("status", "")

    logger.warning(
        "Gemini rate limit [provider=%s metric=%s limit=%s consumer=%s status=%s retry_delay=%s]: %s",
        provider_name,
        metric,
        limit,
        consumer,
        status,
        retry_delay,
        e,
    )


def handle_error(e: Exception, provider_name: str) -> NoReturn:
    """Handle Gemini API errors and raise appropriate exceptions.

    Args:
        e: The caught exception
        provider_name: Provider name for error context

    Raises:
        RateLimitError: For rate limit/quota errors
        AuthenticationError: For auth errors
        ProviderError: For other errors
    """
    from app.adapters.base import AuthenticationError, ProviderError, RateLimitError

    status_code = _extract_status_code(e)
    error_str = str(e).lower()

    if _is_rate_limit_error(status_code, error_str):
        quota = extract_gemini_quota_details(e)
        _log_rate_limit(e, provider_name, quota)
        raise RateLimitError(
            provider_name,
            retry_after=_parse_retry_delay(quota.get("retry_delay")),
            quota_details=quota,
        ) from e

    if _is_auth_error(status_code, error_str):
        logger.error(f"Gemini auth error: {e}")
        raise AuthenticationError(provider_name) from e

    logger.error(f"Gemini API error: {e}")
    retriable = _is_retriable_error(status_code, str(e))

    raise ProviderError(
        str(e),
        provider=provider_name,
        retriable=retriable,
        status_code=status_code,
    ) from e


def _parse_retry_delay(delay_str: str | None) -> float | None:
    """Parse a retry delay string (e.g. '30s', '1m0s') into seconds."""
    if not delay_str:
        return None
    total = 0.0
    for match in re.finditer(r"(\d+(?:\.\d+)?)(ms|s|m|h)", delay_str):
        num, unit = float(match.group(1)), match.group(2)
        if unit == "ms":
            total += num / 1000
        elif unit == "s":
            total += num
        elif unit == "m":
            total += num * 60
        elif unit == "h":
            total += num * 3600
    return total if total > 0 else None


def _extract_status_code(e: Exception) -> int | None:
    """Extract HTTP status code from exception."""
    # Prefer .code attribute (google.genai.errors.APIError)
    code = getattr(e, "code", None)
    if isinstance(code, int):
        return code
    match = re.search(r"\b(4\d{2}|5\d{2})\b", str(e))
    return int(match.group(1)) if match else None


def _is_rate_limit_error(status_code: int | None, error_str: str) -> bool:
    """Check if error is a rate limit error.

    Args:
        status_code: HTTP status code
        error_str: Error message (lowercase)

    Returns:
        True if rate limit error
    """
    return status_code == 429 or "rate" in error_str or "quota" in error_str


def _is_auth_error(status_code: int | None, error_str: str) -> bool:
    """Check if error is an authentication error.

    Args:
        status_code: HTTP status code
        error_str: Error message (lowercase)

    Returns:
        True if auth error
    """
    return status_code in (401, 403) or "api key" in error_str


def _is_retriable_error(status_code: int | None, error_message: str) -> bool:
    """Check if error is retriable (5xx errors).

    Args:
        status_code: HTTP status code
        error_message: Full error message

    Returns:
        True if error should be retried
    """
    if status_code and 500 <= status_code < 600:
        return True

    return any(code in error_message for code in ("500", "502", "503", "504"))
