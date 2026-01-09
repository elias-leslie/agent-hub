"""Rate limit handling with queue and exponential backoff."""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting behavior."""

    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    backoff_factor: float = 2.0
    max_retries: int = 5
    max_queue_size: int = 100


@dataclass
class ProviderState:
    """Rate limit state for a single provider."""

    provider: str
    is_rate_limited: bool = False
    rate_limited_until: float = 0.0
    consecutive_failures: int = 0
    last_success_time: float = field(default_factory=time.time)

    def mark_rate_limited(self, retry_after: float | None = None) -> float:
        """
        Mark provider as rate limited.

        Args:
            retry_after: Optional retry-after hint from provider

        Returns:
            Time in seconds until rate limit clears
        """
        self.is_rate_limited = True
        self.consecutive_failures += 1

        if retry_after:
            # Use provider's hint
            backoff = retry_after
        else:
            # Calculate exponential backoff
            config = RateLimitConfig()
            backoff = min(
                config.initial_backoff_seconds * (config.backoff_factor ** self.consecutive_failures),
                config.max_backoff_seconds,
            )

        self.rate_limited_until = time.time() + backoff
        logger.info(f"Provider {self.provider} rate limited for {backoff:.1f}s")
        return backoff

    def mark_success(self) -> None:
        """Mark successful request, reset failure state."""
        self.is_rate_limited = False
        self.consecutive_failures = 0
        self.last_success_time = time.time()

    def is_available(self) -> bool:
        """Check if provider is available (not rate limited or limit expired)."""
        if not self.is_rate_limited:
            return True
        if time.time() >= self.rate_limited_until:
            self.is_rate_limited = False
            return True
        return False

    def time_until_available(self) -> float:
        """Get seconds until provider becomes available."""
        if self.is_available():
            return 0.0
        return max(0.0, self.rate_limited_until - time.time())


class RateLimiter:
    """
    Rate limiter with per-provider tracking and request queue.

    Features:
    - Tracks rate limit state per provider
    - Queues requests when rate limited
    - Exponential backoff with configurable parameters
    - Auto-fallback to alternate provider
    """

    def __init__(self, config: RateLimitConfig | None = None):
        """
        Initialize rate limiter.

        Args:
            config: Rate limit configuration. Uses defaults if not provided.
        """
        self._config = config or RateLimitConfig()
        self._provider_states: dict[str, ProviderState] = {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=self._config.max_queue_size)
        self._lock = asyncio.Lock()

    def _get_state(self, provider: str) -> ProviderState:
        """Get or create state for provider."""
        if provider not in self._provider_states:
            self._provider_states[provider] = ProviderState(provider=provider)
        return self._provider_states[provider]

    def is_provider_available(self, provider: str) -> bool:
        """Check if a provider is available for requests."""
        return self._get_state(provider).is_available()

    def mark_rate_limited(self, provider: str, retry_after: float | None = None) -> float:
        """
        Mark a provider as rate limited.

        Args:
            provider: Provider name
            retry_after: Optional retry-after hint

        Returns:
            Backoff duration in seconds
        """
        return self._get_state(provider).mark_rate_limited(retry_after)

    def mark_success(self, provider: str) -> None:
        """Mark a successful request for a provider."""
        self._get_state(provider).mark_success()

    def get_available_provider(self, providers: list[str]) -> str | None:
        """
        Get the first available provider from the list.

        Args:
            providers: Ordered list of provider names

        Returns:
            First available provider name, or None if all rate limited
        """
        for provider in providers:
            if self.is_provider_available(provider):
                return provider
        return None

    def get_min_wait_time(self, providers: list[str]) -> float:
        """
        Get minimum time until any provider becomes available.

        Args:
            providers: List of provider names

        Returns:
            Seconds until first provider available
        """
        if not providers:
            return 0.0

        wait_times = [self._get_state(p).time_until_available() for p in providers]
        return min(wait_times)

    async def execute_with_retry(
        self,
        provider: str,
        operation: Callable[[], T],
        on_rate_limit: Callable[[str, float], None] | None = None,
    ) -> T:
        """
        Execute an operation with automatic retry on rate limit.

        Args:
            provider: Provider name
            operation: Async operation to execute
            on_rate_limit: Optional callback when rate limited

        Returns:
            Result of the operation

        Raises:
            Exception: If max retries exceeded
        """
        state = self._get_state(provider)
        retries = 0

        while retries < self._config.max_retries:
            # Wait if rate limited
            wait_time = state.time_until_available()
            if wait_time > 0:
                logger.debug(f"Waiting {wait_time:.1f}s for {provider} rate limit")
                await asyncio.sleep(wait_time)

            try:
                result = await operation()
                self.mark_success(provider)
                return result

            except Exception as e:
                # Check if it's a rate limit error
                error_str = str(e).lower()
                if "429" in str(e) or "rate" in error_str or "limit" in error_str:
                    # Extract retry-after if available
                    retry_after = None
                    if hasattr(e, "retry_after"):
                        retry_after = e.retry_after

                    backoff = self.mark_rate_limited(provider, retry_after)

                    if on_rate_limit:
                        on_rate_limit(provider, backoff)

                    retries += 1
                    continue
                else:
                    # Not a rate limit error, re-raise
                    raise

        raise Exception(f"Max retries ({self._config.max_retries}) exceeded for {provider}")

    def get_stats(self) -> dict[str, dict]:
        """Get rate limit statistics for all providers."""
        return {
            provider: {
                "is_rate_limited": state.is_rate_limited,
                "consecutive_failures": state.consecutive_failures,
                "time_until_available": state.time_until_available(),
                "last_success": state.last_success_time,
            }
            for provider, state in self._provider_states.items()
        }


# Global rate limiter instance
_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter
