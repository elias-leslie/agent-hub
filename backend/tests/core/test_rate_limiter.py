"""Tests for rate limiter."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from app.services.rate_limiter import (
    ProviderState,
    RateLimitConfig,
    RateLimiter,
)


class TestProviderState:
    """Tests for ProviderState."""

    def test_initial_state_available(self):
        """Provider should be available initially."""
        state = ProviderState(provider="claude")
        assert state.is_available() is True
        assert state.is_rate_limited is False

    def test_mark_rate_limited(self):
        """Marking rate limited should set state."""
        state = ProviderState(provider="claude")
        backoff = state.mark_rate_limited()

        assert state.is_rate_limited is True
        assert state.consecutive_failures == 1
        assert backoff > 0

    def test_mark_rate_limited_with_retry_after(self):
        """Should use retry_after hint when provided."""
        state = ProviderState(provider="claude")
        backoff = state.mark_rate_limited(retry_after=30.0)

        assert backoff == 30.0

    def test_exponential_backoff(self):
        """Consecutive failures should increase backoff exponentially."""
        state = ProviderState(provider="claude")

        backoff1 = state.mark_rate_limited()
        # Reset for next test
        state.rate_limited_until = 0

        backoff2 = state.mark_rate_limited()

        assert backoff2 > backoff1

    def test_mark_success_resets_state(self):
        """Success should reset failure state."""
        state = ProviderState(provider="claude")
        state.mark_rate_limited()
        state.mark_success()

        assert state.is_available() is True
        assert state.consecutive_failures == 0

    def test_time_until_available(self):
        """Should return correct wait time."""
        state = ProviderState(provider="claude")
        state.mark_rate_limited(retry_after=5.0)

        wait = state.time_until_available()
        assert 4.0 < wait <= 5.0  # Allow small timing variance


class TestRateLimiter:
    """Tests for RateLimiter."""

    def test_initial_provider_available(self):
        """All providers should be available initially."""
        limiter = RateLimiter()
        assert limiter.is_provider_available("claude") is True
        assert limiter.is_provider_available("gemini") is True

    def test_mark_rate_limited(self):
        """Should mark provider as rate limited."""
        limiter = RateLimiter()
        limiter.mark_rate_limited("claude")

        assert limiter.is_provider_available("claude") is False

    def test_get_available_provider(self):
        """Should return first available provider."""
        limiter = RateLimiter()
        limiter.mark_rate_limited("claude")

        available = limiter.get_available_provider(["claude", "gemini"])
        assert available == "gemini"

    def test_get_available_provider_none(self):
        """Should return None if all rate limited."""
        limiter = RateLimiter()
        limiter.mark_rate_limited("claude")
        limiter.mark_rate_limited("gemini")

        available = limiter.get_available_provider(["claude", "gemini"])
        assert available is None

    def test_get_min_wait_time(self):
        """Should return minimum wait time."""
        limiter = RateLimiter()
        limiter.mark_rate_limited("claude", retry_after=10.0)
        limiter.mark_rate_limited("gemini", retry_after=5.0)

        min_wait = limiter.get_min_wait_time(["claude", "gemini"])
        assert 4.0 < min_wait <= 5.0

    def test_get_stats(self):
        """Should return stats for all providers."""
        limiter = RateLimiter()
        limiter.mark_rate_limited("claude")
        limiter.mark_success("gemini")

        stats = limiter.get_stats()
        assert "claude" in stats
        assert "gemini" in stats
        assert stats["claude"]["is_rate_limited"] is True
        assert stats["gemini"]["is_rate_limited"] is False

    @pytest.mark.asyncio
    async def test_execute_with_retry_success(self):
        """Should execute operation successfully."""
        limiter = RateLimiter()
        operation = AsyncMock(return_value="result")

        result = await limiter.execute_with_retry("claude", operation)

        assert result == "result"
        operation.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_retry_rate_limit(self):
        """Should retry on rate limit error."""
        limiter = RateLimiter(config=RateLimitConfig(initial_backoff_seconds=0.1))

        # First call fails with rate limit, second succeeds
        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("429 rate limit exceeded")
            return "success"

        result = await limiter.execute_with_retry("claude", operation)

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_execute_with_retry_max_exceeded(self):
        """Should raise after max retries."""
        limiter = RateLimiter(
            config=RateLimitConfig(initial_backoff_seconds=0.01, max_retries=2)
        )

        operation = AsyncMock(side_effect=Exception("429 rate limit"))

        with pytest.raises(Exception, match="Max retries"):
            await limiter.execute_with_retry("claude", operation)

    @pytest.mark.asyncio
    async def test_execute_with_retry_non_rate_limit_error(self):
        """Should re-raise non-rate-limit errors immediately."""
        limiter = RateLimiter()
        operation = AsyncMock(side_effect=ValueError("Some other error"))

        with pytest.raises(ValueError):
            await limiter.execute_with_retry("claude", operation)

        # Should only be called once (no retry)
        operation.assert_called_once()
