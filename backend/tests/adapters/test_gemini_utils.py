"""Tests for Gemini utility functions."""

from __future__ import annotations

import pytest

from app.adapters.base import AuthenticationError, ProviderError, RateLimitError
from app.adapters.gemini_utils import handle_error


def test_handle_error_500() -> None:
    """Test handle_error with 500 status code."""
    error = Exception("500 Internal Server Error")
    with pytest.raises(ProviderError) as exc_info:
        handle_error(error, "gemini")

    assert exc_info.value.status_code == 500
    assert exc_info.value.retriable is True
    assert exc_info.value.provider == "gemini"


def test_handle_error_502() -> None:
    """Test handle_error with 502 status code."""
    error = Exception("502 Bad Gateway")
    with pytest.raises(ProviderError) as exc_info:
        handle_error(error, "gemini")

    assert exc_info.value.status_code == 502
    assert exc_info.value.retriable is True
    assert exc_info.value.provider == "gemini"


def test_handle_error_503() -> None:
    """Test handle_error with 503 status code."""
    error = Exception("503 Service Unavailable")
    with pytest.raises(ProviderError) as exc_info:
        handle_error(error, "gemini")

    assert exc_info.value.status_code == 503
    assert exc_info.value.retriable is True
    assert exc_info.value.provider == "gemini"


def test_handle_error_504() -> None:
    """Test handle_error with 504 status code."""
    error = Exception("504 Gateway Timeout")
    with pytest.raises(ProviderError) as exc_info:
        handle_error(error, "gemini")

    assert exc_info.value.status_code == 504
    assert exc_info.value.retriable is True
    assert exc_info.value.provider == "gemini"


def test_handle_error_429() -> None:
    """Test handle_error with 429 status code (RateLimitError)."""
    error = Exception("429 Too Many Requests")
    with pytest.raises(RateLimitError) as exc_info:
        handle_error(error, "gemini")

    assert exc_info.value.status_code == 429
    assert exc_info.value.retriable is True
    assert exc_info.value.provider == "gemini"


def test_handle_error_401() -> None:
    """Test handle_error with 401 status code (AuthenticationError)."""
    error = Exception("401 Unauthorized")
    with pytest.raises(AuthenticationError) as exc_info:
        handle_error(error, "gemini")

    assert exc_info.value.status_code == 401
    assert exc_info.value.retriable is False
    assert exc_info.value.provider == "gemini"


def test_handle_error_rpc_style() -> None:
    """Test handle_error with RPC style error message."""
    error = Exception("RPC error: code = 503 message = Service Unavailable")
    with pytest.raises(ProviderError) as exc_info:
        handle_error(error, "gemini")

    assert exc_info.value.status_code == 503
    assert exc_info.value.retriable is True


def test_handle_error_no_code() -> None:
    """Test handle_error with no status code in message."""
    error = Exception("Something went wrong")
    with pytest.raises(ProviderError) as exc_info:
        handle_error(error, "gemini")

    assert exc_info.value.status_code is None
    assert exc_info.value.retriable is False
