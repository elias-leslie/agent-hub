"""Error handling for Gemini adapter."""

import logging
import re
from typing import NoReturn

logger = logging.getLogger(__name__)


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
        logger.warning(f"Gemini rate limit: {e}")
        raise RateLimitError(provider_name) from e

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


def _extract_status_code(e: Exception) -> int | None:
    """Extract HTTP status code from exception.

    Args:
        e: Exception to parse

    Returns:
        Status code if found, None otherwise
    """
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
