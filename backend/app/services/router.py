"""Model router with fallback and tier-based selection support."""

import hashlib
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

import redis.asyncio as aioredis

from app.adapters.base import (
    CircuitBreakerError,
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    RateLimitError,
)
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.services.tier_classifier import Tier, classify_request, get_model_for_tier

logger = logging.getLogger(__name__)

# Thrashing detection constants
THRASHING_THRESHOLD = 2  # Warn after this many consecutive identical errors
CIRCUIT_BREAKER_THRESHOLD = 5  # Open circuit after this many
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
class ErrorSignature:
    """Signature for identifying identical errors."""

    error_type: str
    error_message_hash: str
    provider: str
    model: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class CircuitBreakerState:
    """Per-provider circuit breaker state."""

    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    last_error_signature: str | None = None
    cooldown_until: float | None = None


# Default provider chain for fallback
DEFAULT_PROVIDER_CHAIN = ["claude", "gemini"]

# Global metrics for thrashing/circuit breaker (updated by router)
_thrashing_metrics: dict[str, int] = {
    "thrashing_events_total": 0,
    "circuit_breaker_trips_total": 0,
}


def get_thrashing_metrics() -> dict[str, int]:
    """Get current thrashing and circuit breaker metrics."""
    return _thrashing_metrics.copy()


def _increment_thrashing_events() -> None:
    """Increment thrashing events counter."""
    _thrashing_metrics["thrashing_events_total"] += 1


def _increment_circuit_trips() -> None:
    """Increment circuit breaker trips counter."""
    _thrashing_metrics["circuit_breaker_trips_total"] += 1


# Global router instance
_router_instance: "ModelRouter | None" = None

# Global Redis client for circuit breaker
_redis_client: aioredis.Redis | None = None


async def _get_redis_client() -> aioredis.Redis | None:
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


def get_router() -> "ModelRouter":
    """Get or create the global ModelRouter instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ModelRouter()
    return _router_instance


class ModelRouter:
    """
    Routes completion requests to providers with fallback support.

    When the primary provider fails (rate limit, error), automatically
    tries the next provider in the chain. Includes thrashing detection
    to avoid repeated identical failures.
    """

    def __init__(
        self,
        provider_chain: list[str] | None = None,
        adapter_factory: dict[str, Callable[[], ProviderAdapter]] | None = None,
    ):
        """
        Initialize router with provider chain.

        Args:
            provider_chain: Order of providers to try. Defaults to ["claude", "gemini"].
            adapter_factory: Factory functions to create adapters. Defaults to built-in adapters.
        """
        self._provider_chain = provider_chain or DEFAULT_PROVIDER_CHAIN
        self._adapter_factory = adapter_factory or {
            "claude": ClaudeAdapter,
            "gemini": GeminiAdapter,
        }
        self._adapters: dict[str, ProviderAdapter] = {}

        # Thrashing detection state
        self._error_history: deque[ErrorSignature] = deque(maxlen=10)
        self._circuit_state: dict[str, CircuitBreakerState] = {}

    def _get_adapter(self, provider: str) -> ProviderAdapter:
        """Get or create adapter for provider."""
        if provider not in self._adapters:
            factory = self._adapter_factory.get(provider)
            if not factory:
                raise ValueError(f"Unknown provider: {provider}")
            self._adapters[provider] = factory()
        return self._adapters[provider]

    def _determine_primary_provider(self, model: str) -> str:
        """Determine primary provider from model name."""
        model_lower = model.lower()
        if "claude" in model_lower:
            return "claude"
        elif "gemini" in model_lower:
            return "gemini"
        # Default to first in chain
        return self._provider_chain[0]

    def _get_fallback_chain(self, primary: str) -> list[str]:
        """Get provider chain starting with primary, then others."""
        chain = [primary]
        for provider in self._provider_chain:
            if provider != primary and provider not in chain:
                chain.append(provider)
        return chain

    def _compute_error_signature(self, error: Exception, provider: str, model: str) -> str:
        """Compute a signature for an error to detect identical failures."""
        error_type = type(error).__name__
        # Normalize error message: strip variable parts like timestamps, IDs
        error_msg = str(error)
        # Hash the normalized message for comparison
        msg_hash = hashlib.md5(error_msg.encode(), usedforsecurity=False).hexdigest()[:8]
        return f"{error_type}:{provider}:{model}:{msg_hash}"

    def _check_thrashing(self, current_sig: str, history_count: int) -> int:
        """
        Check for thrashing (consecutive identical errors).

        Args:
            current_sig: Signature of current error
            history_count: Number of items in history BEFORE adding current error

        Returns:
            Number of consecutive identical errors including current.
        """
        count = 1  # Current error counts as 1
        # Only check items that were in history BEFORE we added the current error
        for sig in list(self._error_history)[:history_count][::-1]:
            full_sig = f"{sig.error_type}:{sig.provider}:{sig.model}:{sig.error_message_hash}"
            if full_sig == current_sig:
                count += 1
            else:
                break
        return count

    def _record_error(self, error: Exception, provider: str, model: str) -> int:
        """
        Record an error and return consecutive identical error count.

        Returns:
            Number of consecutive identical errors.
        """
        error_type = type(error).__name__
        error_msg = str(error)
        msg_hash = hashlib.md5(error_msg.encode(), usedforsecurity=False).hexdigest()[:8]

        # Capture history length BEFORE adding new error
        history_len = len(self._error_history)

        sig = ErrorSignature(
            error_type=error_type,
            error_message_hash=msg_hash,
            provider=provider,
            model=model,
        )
        self._error_history.append(sig)

        full_sig = f"{error_type}:{provider}:{model}:{msg_hash}"
        return self._check_thrashing(full_sig, history_len)

    def _get_circuit_state(self, provider: str) -> CircuitBreakerState:
        """Get or create circuit breaker state for provider (in-memory fallback)."""
        if provider not in self._circuit_state:
            self._circuit_state[provider] = CircuitBreakerState()
        return self._circuit_state[provider]

    def _redis_key(self, provider: str) -> str:
        """Get Redis key for provider circuit breaker state."""
        return f"{REDIS_CIRCUIT_KEY_PREFIX}:{provider}"

    async def _get_circuit_state_from_redis(
        self, provider: str, client: aioredis.Redis
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
        self, provider: str, state: CircuitBreakerState, client: aioredis.Redis
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

    async def _check_circuit(self, provider: str) -> bool:
        """
        Check if circuit allows requests.

        Reads from Redis if available, falls back to in-memory.

        Returns:
            True if request should proceed, False if blocked.
        """
        # Try Redis first
        redis = await _get_redis_client()
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

    async def _on_success(self, provider: str) -> None:
        """Handle successful request - reset circuit state."""
        state = self._get_circuit_state(provider)
        if state.state != CircuitState.CLOSED:
            logger.info(f"Circuit closed for {provider} after successful request")
        state.state = CircuitState.CLOSED
        state.consecutive_failures = 0
        state.last_error_signature = None
        state.cooldown_until = None

        # Save to Redis
        redis = await _get_redis_client()
        if redis:
            await self._save_circuit_state_to_redis(provider, state, redis)

    async def _on_failure(self, provider: str, model: str, error: Exception) -> None:
        """Handle failed request - update circuit state and check thrashing."""
        consecutive = self._record_error(error, provider, model)
        state = self._get_circuit_state(provider)

        state.consecutive_failures = consecutive
        state.last_error_signature = self._compute_error_signature(error, provider, model)

        if consecutive >= THRASHING_THRESHOLD:
            _increment_thrashing_events()
            logger.warning(
                f"Thrashing detected: {consecutive} consecutive identical errors "
                f"for {provider}/{model}"
            )

        # Save to Redis
        redis = await _get_redis_client()

        if consecutive >= CIRCUIT_BREAKER_THRESHOLD:
            _increment_circuit_trips()
            state.state = CircuitState.OPEN
            state.cooldown_until = time.time() + CIRCUIT_BREAKER_COOLDOWN
            logger.error(
                f"Circuit breaker OPEN for {provider}: "
                f"{consecutive} consecutive failures, cooldown until "
                f"{time.strftime('%H:%M:%S', time.localtime(state.cooldown_until))}"
            )
            # Save to Redis before raising
            if redis:
                await self._save_circuit_state_to_redis(provider, state, redis)
            raise CircuitBreakerError(
                provider=provider,
                consecutive_failures=consecutive,
                last_error_signature=state.last_error_signature,
                cooldown_until=state.cooldown_until,
            )

        # Save non-threshold state to Redis
        if redis:
            await self._save_circuit_state_to_redis(provider, state, redis)

    def reset_circuit(self, provider: str) -> None:
        """Manually reset circuit breaker for a provider."""
        if provider in self._circuit_state:
            self._circuit_state[provider] = CircuitBreakerState()
            logger.info(f"Circuit manually reset for {provider}")

    def get_circuit_status(self) -> dict[str, dict]:
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

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        auto_tier: bool = False,
        **kwargs,
    ) -> CompletionResult:
        """
        Generate completion with automatic fallback and optional tier-based selection.

        Tries primary provider first, falls back to others on failure.
        Logs which provider actually served the request.
        Includes thrashing detection and circuit breaker protection.

        Args:
            messages: Conversation messages
            model: Model identifier. If None and auto_tier=True, selects based on complexity.
            max_tokens: Maximum response tokens
            temperature: Sampling temperature
            auto_tier: If True and model not specified, auto-select model based on complexity
            **kwargs: Additional provider-specific parameters

        Returns:
            CompletionResult from the provider that succeeded

        Raises:
            ProviderError: If all providers fail
            CircuitBreakerError: If circuit breaker is open for provider
        """
        # Auto-select model based on tier if requested
        tier: Tier | None = None
        if auto_tier and not model:
            # Extract prompt from last user message for classification
            prompt = ""
            for msg in reversed(messages):
                if msg.role == "user":
                    # Handle both str and list content
                    if isinstance(msg.content, str):
                        prompt = msg.content
                    else:
                        # Extract text from content blocks
                        prompt = " ".join(
                            block.get("text", "")
                            for block in msg.content
                            if isinstance(block, dict) and block.get("type") == "text"
                        )
                    break
            tier = classify_request(prompt)
            model = get_model_for_tier(tier, self._provider_chain[0])
            logger.info(f"Auto-tier selected: tier={tier}, model={model}")

        # Default model if still not set
        if not model:
            model = get_model_for_tier(Tier.TIER_2, self._provider_chain[0])

        primary = self._determine_primary_provider(model)
        chain = self._get_fallback_chain(primary)

        last_error: Exception | None = None

        for i, provider in enumerate(chain):
            # Check circuit breaker before attempting request
            if not await self._check_circuit(provider):
                state = self._get_circuit_state(provider)
                logger.warning(f"Circuit open for {provider}, skipping")
                last_error = CircuitBreakerError(
                    provider=provider,
                    consecutive_failures=state.consecutive_failures,
                    last_error_signature=state.last_error_signature or "",
                    cooldown_until=state.cooldown_until,
                )
                continue

            try:
                adapter = self._get_adapter(provider)

                # For fallback providers, we may need to map the model
                effective_model = model
                if provider != primary:
                    effective_model = self._map_model_to_provider(model, provider)
                    logger.info(
                        f"Fallback: {primary} -> {provider}, model: {model} -> {effective_model}"
                    )

                result = await adapter.complete(
                    messages=messages,
                    model=effective_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )

                # Success - reset circuit state
                await self._on_success(provider)

                if i > 0:
                    logger.info(f"Request served by fallback provider: {provider}")
                else:
                    logger.debug(f"Request served by primary provider: {provider}")

                return result

            except RateLimitError as e:
                logger.warning(f"Rate limit on {provider}, trying next provider")
                await self._on_failure(provider, model, e)
                last_error = e
                continue

            except CircuitBreakerError:
                # Re-raise circuit breaker errors (from _on_failure)
                raise

            except ProviderError as e:
                if e.retriable:
                    logger.warning(f"Retriable error on {provider}: {e}, trying next provider")
                    await self._on_failure(provider, model, e)
                    last_error = e
                    continue
                else:
                    # Non-retriable error (e.g., auth) - don't try other providers
                    raise

            except ValueError as e:
                # Configuration error (e.g., missing API key) - try next provider
                logger.warning(f"Config error for {provider}: {e}, trying next provider")
                last_error = e
                continue

        # All providers failed
        logger.error(f"All providers failed. Last error: {last_error}")
        if isinstance(last_error, ProviderError):
            raise last_error
        raise ProviderError(
            f"All providers failed: {last_error}",
            provider="router",
            retriable=False,
        )

    def _map_model_to_provider(self, original_model: str, target_provider: str) -> str:
        """
        Map a model from one provider to an equivalent in another.

        This is a simple mapping for fallback scenarios.
        """
        from app.constants import (
            CLAUDE_SONNET,
            CLAUDE_TO_GEMINI_MAP,
            GEMINI_FLASH,
            GEMINI_TO_CLAUDE_MAP,
        )

        if target_provider == "gemini":
            return CLAUDE_TO_GEMINI_MAP.get(original_model, GEMINI_FLASH)
        elif target_provider == "claude":
            return GEMINI_TO_CLAUDE_MAP.get(original_model, CLAUDE_SONNET)
        else:
            return original_model
