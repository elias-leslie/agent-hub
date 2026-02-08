"""Tests for app.adapters.errors — retry logic and error classification."""

from __future__ import annotations

from app.adapters.errors import ProviderError, is_retriable_error


class _ExcWithStatusCode(Exception):
    """Exception with integer status_code attribute."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class _ExcWithCode(Exception):
    """Exception with integer code attribute (google.genai.errors.APIError pattern)."""

    def __init__(self, code: int, status: str):
        self.code = code
        self.status = status
        super().__init__(f"{code} {status}")


class _ExcWithStringStatus(Exception):
    """Exception with only a string status attribute (no int code)."""

    def __init__(self, status: str):
        self.status = status
        super().__init__(status)


class _PlainException(Exception):
    """Exception with no status/code attributes."""


class TestIsRetriableError:
    def test_provider_error_retriable_flag(self) -> None:
        err = ProviderError("transient", provider="test", retriable=True)
        assert is_retriable_error(err) is True

    def test_provider_error_not_retriable(self) -> None:
        err = ProviderError("permanent", provider="test", retriable=False)
        assert is_retriable_error(err) is False

    def test_provider_error_429_status_code(self) -> None:
        err = ProviderError("rate limit", provider="test", retriable=False, status_code=429)
        assert is_retriable_error(err) is True

    def test_provider_error_503_status_code(self) -> None:
        err = ProviderError("unavailable", provider="test", retriable=False, status_code=503)
        assert is_retriable_error(err) is True

    def test_provider_error_500_status_code(self) -> None:
        err = ProviderError("server error", provider="test", retriable=False, status_code=500)
        assert is_retriable_error(err) is True

    def test_provider_error_400_not_retriable(self) -> None:
        err = ProviderError("bad request", provider="test", retriable=False, status_code=400)
        assert is_retriable_error(err) is False

    def test_generic_exception_with_status_code_429(self) -> None:
        assert is_retriable_error(_ExcWithStatusCode(429)) is True

    def test_generic_exception_with_status_code_503(self) -> None:
        assert is_retriable_error(_ExcWithStatusCode(503)) is True

    def test_generic_exception_with_status_code_500(self) -> None:
        assert is_retriable_error(_ExcWithStatusCode(500)) is True

    def test_generic_exception_with_status_code_400_not_retriable(self) -> None:
        assert is_retriable_error(_ExcWithStatusCode(400)) is False

    def test_genai_api_error_pattern_503_unavailable(self) -> None:
        """google.genai.errors.APIError has .code (int) and .status (str)."""
        err = _ExcWithCode(503, "UNAVAILABLE")
        assert is_retriable_error(err) is True

    def test_genai_api_error_pattern_429_resource_exhausted(self) -> None:
        err = _ExcWithCode(429, "RESOURCE_EXHAUSTED")
        assert is_retriable_error(err) is True

    def test_genai_api_error_pattern_400_invalid_argument(self) -> None:
        err = _ExcWithCode(400, "INVALID_ARGUMENT")
        assert is_retriable_error(err) is False

    def test_string_status_no_type_error(self) -> None:
        """Regression: string .status must not cause '>=' TypeError."""
        err = _ExcWithStringStatus("UNAVAILABLE")
        assert is_retriable_error(err) is True

    def test_string_status_resource_exhausted(self) -> None:
        err = _ExcWithStringStatus("RESOURCE_EXHAUSTED")
        assert is_retriable_error(err) is True

    def test_string_status_internal(self) -> None:
        err = _ExcWithStringStatus("INTERNAL")
        assert is_retriable_error(err) is True

    def test_string_status_deadline_exceeded(self) -> None:
        err = _ExcWithStringStatus("DEADLINE_EXCEEDED")
        assert is_retriable_error(err) is True

    def test_string_status_not_found_not_retriable(self) -> None:
        err = _ExcWithStringStatus("NOT_FOUND")
        assert is_retriable_error(err) is False

    def test_string_status_permission_denied_not_retriable(self) -> None:
        err = _ExcWithStringStatus("PERMISSION_DENIED")
        assert is_retriable_error(err) is False

    def test_plain_exception_not_retriable(self) -> None:
        assert is_retriable_error(_PlainException("oops")) is False

    def test_no_crash_on_none_attributes(self) -> None:
        err = Exception("generic")
        assert is_retriable_error(err) is False
