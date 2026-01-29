"""Error tracking and thrashing detection for router."""

import hashlib
import logging
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Thrashing detection constant
THRASHING_THRESHOLD = 2  # Warn after this many consecutive identical errors


@dataclass
class ErrorSignature:
    """Signature for identifying identical errors."""

    error_type: str
    error_message_hash: str
    provider: str
    model: str
    timestamp: float = field(default_factory=time.time)


# Global metrics for thrashing (updated by router)
_thrashing_metrics: dict[str, int] = {
    "thrashing_events_total": 0,
    "circuit_breaker_trips_total": 0,
}


def get_thrashing_metrics() -> dict[str, int]:
    """Get current thrashing and circuit breaker metrics."""
    return _thrashing_metrics.copy()


def increment_thrashing_events() -> None:
    """Increment thrashing events counter."""
    _thrashing_metrics["thrashing_events_total"] += 1


def increment_circuit_trips() -> None:
    """Increment circuit breaker trips counter."""
    _thrashing_metrics["circuit_breaker_trips_total"] += 1


class ErrorTracker:
    """Tracks errors and detects thrashing patterns."""

    def __init__(self, history_size: int = 10):
        """Initialize error tracker.

        Args:
            history_size: Maximum number of errors to keep in history.
        """
        self._error_history: deque[ErrorSignature] = deque(maxlen=history_size)

    def compute_error_signature(self, error: Exception, provider: str, model: str) -> str:
        """Compute a signature for an error to detect identical failures."""
        error_type = type(error).__name__
        # Normalize error message: strip variable parts like timestamps, IDs
        error_msg = str(error)
        # Hash the normalized message for comparison
        msg_hash = hashlib.md5(error_msg.encode(), usedforsecurity=False).hexdigest()[:8]
        return f"{error_type}:{provider}:{model}:{msg_hash}"

    def _check_thrashing(self, current_sig: str, history_count: int) -> int:
        """Check for thrashing (consecutive identical errors).

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

    def record_error(self, error: Exception, provider: str, model: str) -> int:
        """Record an error and return consecutive identical error count.

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
        consecutive = self._check_thrashing(full_sig, history_len)

        # Log if thrashing detected
        if consecutive >= THRASHING_THRESHOLD:
            increment_thrashing_events()
            logger.warning(
                f"Thrashing detected: {consecutive} consecutive identical errors "
                f"for {provider}/{model}"
            )

        return consecutive
