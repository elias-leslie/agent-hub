"""Circuit breaker implementation for provider failure management."""

import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio.client import Redis as AsyncRedis

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Circuit breaker constants
CIRCUIT_BREAKER_THRESHOLD = 5  # Open circuit after this many consecutive failures
CIRCUIT_BREAKER_COOLDOWN = 60.0  # Seconds before half-open

# Redis keys for circuit breaker state (shared across processes)
REDIS_CIRCUIT_KEY_PREFIX = "agent-hub:circuit-breaker"
REDIS_CIRCUIT_TTL = 300  # 5 minutes TTL to prevent stale state


class CircuitState(Enum):
    """Circuit breaker state."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Rejecting requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerState:
    """Per-provider circuit breaker state."""

    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    last_error_signature: str | None = None
    cooldown_until: float | None = None


# Global Redis client for circuit breaker
_redis_client: "AsyncRedis[str] | None" = None


async def get_redis_client() -> "AsyncRedis[str] | None":
    """Get or create Redis client for circuit breaker state.

    Returns None if Redis is unavailable (falls back to in-memory).
    """
    global _redis_client
    if _redis_client is None:
        try:
            from app.config import get_settings

            settings = get_settings()
            _redis_client = aioredis.from_url(
                settings.agent_hub_redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            # Test connection
            await _redis_client.ping()
            logger.info("Redis connected for circuit breaker")
        except Exception as e:
            logger.warning(f"Redis unavailable for circuit breaker, using in-memory: {e}")
            return None
    return _redis_client


class CircuitBreakerManager:
    """Manages circuit breaker state for providers."""

    def __init__(self, provider_chain: list[str]):
        """Initialize circuit breaker manager.

        Args:
            provider_chain: List of provider names to manage.
        """
        self._provider_chain = provider_chain
        self._circuit_state: dict[str, CircuitBreakerState] = {}

    def _get_circuit_state(self, provider: str) -> CircuitBreakerState:
        """Get or create circuit breaker state for provider (in-memory fallback)."""
        if provider not in self._circuit_state:
            self._circuit_state[provider] = CircuitBreakerState()
        return self._circuit_state[provider]

    def _redis_key(self, provider: str) -> str:
        """Get Redis key for provider circuit breaker state."""
        return f"{REDIS_CIRCUIT_KEY_PREFIX}:{provider}"

    async def _get_circuit_state_from_redis(
        self, provider: str, client: "AsyncRedis[str]"
    ) -> CircuitBreakerState | None:
        """Get circuit state from Redis if available."""
        try:
            data = await client.get(self._redis_key(provider))
            if data:
                state_dict = json.loads(data)
                return CircuitBreakerState(
                    state=CircuitState(state_dict["state"]),
                    consecutive_failures=state_dict["consecutive_failures"],
                    last_error_signature=state_dict.get("last_error_signature"),
                    cooldown_until=state_dict.get("cooldown_until"),
                )
        except Exception as e:
            logger.warning(f"Error reading circuit state from Redis: {e}")
        return None

    async def _save_circuit_state_to_redis(
        self, provider: str, state: CircuitBreakerState, client: "AsyncRedis[str]"
    ) -> None:
        """Save circuit state to Redis with TTL."""
        try:
            state_dict = {
                "state": state.state.value,
                "consecutive_failures": state.consecutive_failures,
                "last_error_signature": state.last_error_signature,
                "cooldown_until": state.cooldown_until,
            }
            await client.set(
                self._redis_key(provider),
                json.dumps(state_dict),
                ex=REDIS_CIRCUIT_TTL,
            )
        except Exception as e:
            logger.warning(f"Error saving circuit state to Redis: {e}")

    async def check_circuit(self, provider: str) -> bool:
        """Check if circuit allows requests.

        Reads from Redis if available, falls back to in-memory.

        Returns:
            True if request should proceed, False if blocked.
        """
        # Try Redis first
        redis = await get_redis_client()
        if redis:
            redis_state = await self._get_circuit_state_from_redis(provider, redis)
            if redis_state:
                # Sync in-memory state with Redis
                self._circuit_state[provider] = redis_state

        state = self._get_circuit_state(provider)

        if state.state == CircuitState.CLOSED:
            return True

        if state.state == CircuitState.OPEN:
            # Check if cooldown has passed
            if state.cooldown_until and time.time() >= state.cooldown_until:
                state.state = CircuitState.HALF_OPEN
                logger.info(f"Circuit half-open for {provider}, allowing test request")
                # Save half-open state to Redis
                if redis:
                    await self._save_circuit_state_to_redis(provider, state, redis)
                return True
            return False

        # HALF_OPEN: allow one test request
        return True

    async def on_success(self, provider: str) -> None:
        """Handle successful request - reset circuit state."""
        state = self._get_circuit_state(provider)
        if state.state != CircuitState.CLOSED:
            logger.info(f"Circuit closed for {provider} after successful request")
        state.state = CircuitState.CLOSED
        state.consecutive_failures = 0
        state.last_error_signature = None
        state.cooldown_until = None

        # Save to Redis
        redis = await get_redis_client()
        if redis:
            await self._save_circuit_state_to_redis(provider, state, redis)

    async def on_failure(
        self, provider: str, consecutive: int, error_signature: str
    ) -> CircuitBreakerState:
        """Handle failed request - update circuit state.

        Args:
            provider: Provider name
            consecutive: Number of consecutive failures
            error_signature: Signature of the error

        Returns:
            Updated circuit breaker state
        """
        state = self._get_circuit_state(provider)
        state.consecutive_failures = consecutive
        state.last_error_signature = error_signature

        # Save to Redis
        redis = await get_redis_client()

        if consecutive >= CIRCUIT_BREAKER_THRESHOLD:
            state.state = CircuitState.OPEN
            state.cooldown_until = time.time() + CIRCUIT_BREAKER_COOLDOWN
            logger.error(
                f"Circuit breaker OPEN for {provider}: "
                f"{consecutive} consecutive failures, cooldown until "
                f"{time.strftime('%H:%M:%S', time.localtime(state.cooldown_until))}"
            )
            # Save to Redis before returning
            if redis:
                await self._save_circuit_state_to_redis(provider, state, redis)
        elif redis:
            # Save non-threshold state to Redis
            await self._save_circuit_state_to_redis(provider, state, redis)

        return state

    def reset_circuit(self, provider: str) -> None:
        """Manually reset circuit breaker for a provider."""
        if provider in self._circuit_state:
            self._circuit_state[provider] = CircuitBreakerState()
            logger.info(f"Circuit manually reset for {provider}")

    def get_circuit_status(self) -> dict[str, dict[str, str | int | float | None]]:
        """Get current circuit breaker status for all providers."""
        status = {}
        for provider in self._provider_chain:
            state = self._get_circuit_state(provider)
            status[provider] = {
                "state": state.state.value,
                "consecutive_failures": state.consecutive_failures,
                "last_error_signature": state.last_error_signature,
                "cooldown_until": state.cooldown_until,
            }
        return status
