"""Interface contract tests for provider adapters.

These tests ensure all adapters implement the ProviderAdapter protocol
consistently and correctly.
"""

import inspect
from typing import get_type_hints

import pytest

from app.adapters.base import CompletionResult, Message
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter

# All adapter classes that should implement ProviderAdapter
ADAPTER_CLASSES = [ClaudeAdapter, GeminiAdapter]


class TestCommonInterface:
    """Tests that all adapters implement the required interface."""

    @pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
    def test_has_provider_name_property(self, adapter_class):
        """All adapters must have provider_name property."""
        assert hasattr(adapter_class, "provider_name")
        # Check it's a property
        assert isinstance(inspect.getattr_static(adapter_class, "provider_name"), property)

    @pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
    def test_has_complete_method(self, adapter_class):
        """All adapters must have complete method."""
        assert hasattr(adapter_class, "complete")
        assert callable(adapter_class.complete)

    @pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
    def test_has_health_check_method(self, adapter_class):
        """All adapters must have health_check method."""
        assert hasattr(adapter_class, "health_check")
        assert callable(adapter_class.health_check)

    @pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
    def test_complete_signature(self, adapter_class):
        """All adapters must have consistent complete() signature."""
        sig = inspect.signature(adapter_class.complete)
        param_names = list(sig.parameters.keys())

        # Required parameters
        assert "self" in param_names
        assert "messages" in param_names
        assert "model" in param_names

        # Optional parameters with defaults
        assert "max_tokens" in param_names
        assert "temperature" in param_names

    @pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
    def test_complete_is_async(self, adapter_class):
        """complete() must be an async method."""
        assert inspect.iscoroutinefunction(adapter_class.complete)

    @pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
    def test_health_check_is_async(self, adapter_class):
        """health_check() must be an async method."""
        assert inspect.iscoroutinefunction(adapter_class.health_check)


class TestReturnTypes:
    """Tests that adapters return correct types."""

    @pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
    def test_provider_name_returns_string(self, adapter_class):
        """provider_name must be annotated to return str."""
        # Get the fget of the property and check its return annotation
        prop = inspect.getattr_static(adapter_class, "provider_name")
        if hasattr(prop.fget, "__annotations__"):
            annotations = prop.fget.__annotations__
            if "return" in annotations:
                assert annotations["return"] is str

    @pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
    def test_complete_returns_completion_result(self, adapter_class):
        """complete() must return CompletionResult."""
        hints = get_type_hints(adapter_class.complete)
        assert "return" in hints
        assert hints["return"] == CompletionResult

    @pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
    def test_health_check_returns_bool(self, adapter_class):
        """health_check() must return bool."""
        hints = get_type_hints(adapter_class.health_check)
        assert "return" in hints
        assert hints["return"] is bool


class TestErrorHandling:
    """Tests for consistent error handling across adapters."""

    def test_adapters_import_same_exceptions(self):
        """All adapters should use the same exception types."""
        from app.adapters.base import (
            AuthenticationError,
            ProviderError,
            RateLimitError,
        )

        # These should be importable
        assert ProviderError is not None
        assert RateLimitError is not None
        assert AuthenticationError is not None

        # RateLimitError should be a subclass of ProviderError
        assert issubclass(RateLimitError, ProviderError)
        assert issubclass(AuthenticationError, ProviderError)

    @pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
    def test_adapter_raises_value_error_without_api_key(self, adapter_class):
        """Adapters should raise ValueError if API key and OAuth both missing."""
        from unittest.mock import patch

        # Claude can use OAuth, so we need to mock out the CLI check
        # Gemini falls back to settings.gemini_api_key, so we need to mock that too
        with (
            patch("app.adapters.claude.shutil.which", return_value=None),
            patch("app.adapters.gemini.settings") as mock_settings,
        ):
            mock_settings.gemini_api_key = ""
            with pytest.raises(ValueError):
                adapter_class(api_key="")


class TestCompletionResultContract:
    """Tests for CompletionResult contract."""

    def test_completion_result_has_required_fields(self):
        """CompletionResult must have all required fields."""
        result = CompletionResult(
            content="test",
            model="test-model",
            provider="test-provider",
            input_tokens=10,
            output_tokens=5,
        )

        assert result.content == "test"
        assert result.model == "test-model"
        assert result.provider == "test-provider"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    def test_completion_result_optional_fields(self):
        """CompletionResult optional fields should have defaults."""
        result = CompletionResult(
            content="test",
            model="test-model",
            provider="test-provider",
            input_tokens=10,
            output_tokens=5,
        )

        # Optional fields should have sensible defaults
        assert result.finish_reason is None
        assert result.raw_response is None


class TestMessageContract:
    """Tests for Message contract."""

    def test_message_has_required_fields(self):
        """Message must have role and content."""
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_message_role_types(self):
        """Message role should accept standard roles."""
        # These should all work
        Message(role="user", content="test")
        Message(role="assistant", content="test")
        Message(role="system", content="test")


class TestRetryLogic:
    """Tests for retry logic (is_retriable_error and with_retry)."""

    def test_is_retriable_error_with_429(self):
        """429 rate limit error should be retriable."""
        from app.adapters.base import ProviderError, is_retriable_error

        error = ProviderError("Rate limited", provider="test", retriable=True, status_code=429)
        assert is_retriable_error(error) is True

    def test_is_retriable_error_with_503(self):
        """503 service unavailable error should be retriable."""
        from app.adapters.base import ProviderError, is_retriable_error

        error = ProviderError("Unavailable", provider="test", retriable=True, status_code=503)
        assert is_retriable_error(error) is True

    def test_is_retriable_error_with_500(self):
        """500 server error should be retriable."""
        from app.adapters.base import ProviderError, is_retriable_error

        error = ProviderError("Server error", provider="test", retriable=True, status_code=500)
        assert is_retriable_error(error) is True

    def test_is_retriable_error_with_401(self):
        """401 auth error should NOT be retriable."""
        from app.adapters.base import ProviderError, is_retriable_error

        error = ProviderError("Unauthorized", provider="test", retriable=False, status_code=401)
        assert is_retriable_error(error) is False

    def test_is_retriable_error_with_retriable_flag(self):
        """ProviderError with retriable=True should be retriable."""
        from app.adapters.base import ProviderError, is_retriable_error

        error = ProviderError("Transient", provider="test", retriable=True)
        assert is_retriable_error(error) is True

    def test_is_retriable_error_with_non_retriable_flag(self):
        """ProviderError with retriable=False should NOT be retriable."""
        from app.adapters.base import ProviderError, is_retriable_error

        error = ProviderError("Permanent", provider="test", retriable=False)
        assert is_retriable_error(error) is False

    def test_with_retry_decorator_exists(self):
        """with_retry decorator should be importable."""
        from app.adapters.base import with_retry

        assert callable(with_retry)

    @pytest.mark.asyncio
    async def test_with_retry_succeeds_on_first_attempt(self):
        """with_retry should succeed immediately if no error."""
        from app.adapters.base import with_retry

        call_count = 0

        @with_retry
        async def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await successful_func()
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_with_retry_retries_on_transient_error(self):
        """with_retry should retry on retriable errors."""
        from app.adapters.base import ProviderError, with_retry

        call_count = 0

        @with_retry
        async def transient_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ProviderError("Transient", provider="test", retriable=True, status_code=503)
            return "success"

        result = await transient_then_success()
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_with_retry_does_not_retry_permanent_error(self):
        """with_retry should NOT retry on non-retriable errors."""
        from app.adapters.base import ProviderError, with_retry

        call_count = 0

        @with_retry
        async def permanent_error():
            nonlocal call_count
            call_count += 1
            raise ProviderError("Permanent", provider="test", retriable=False, status_code=401)

        with pytest.raises(ProviderError):
            await permanent_error()

        assert call_count == 1  # Should only be called once
