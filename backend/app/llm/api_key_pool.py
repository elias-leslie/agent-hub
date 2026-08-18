"""Per-provider API key rotation with failure cooldowns.

Some providers are configured with several keys belonging to separate accounts.
Gemini is the live case: quota is enforced per project, so spreading requests
across accounts multiplies the usable free tier, and a key that has been shut
off (depleted prepay balance, revoked key) must not sink every request that
follows.

The pool keeps a short-lived cooldown per key rather than a health check. A key
that just returned a quota error is skipped until its window is likely to have
rolled over; if every key is cooling, the one closest to recovery is handed back
anyway so a request fails against the live API instead of failing locally.
"""

from __future__ import annotations

import itertools
import re
import time
from dataclasses import dataclass, field
from threading import Lock

# Free-tier quota windows are per minute, so a rate-limited key is worth
# retrying soon. A billing stop or a revoked key will not fix itself, and
# retrying one costs a full round trip, so those wait considerably longer.
RATE_LIMIT_COOLDOWN_SECONDS = 60.0
BILLING_COOLDOWN_SECONDS = 900.0
AUTH_COOLDOWN_SECONDS = 3600.0

_BILLING_MARKERS = (
    "prepayment credits are depleted",
    "billing account",
    "quota exceeded for quota metric",
    "free_tier",
    "insufficient",
)
_AUTH_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "permission_denied",
    "unauthenticated",
    "consumer_suspended",
)


def classify_key_failure(error: BaseException) -> float | None:
    """Return how long to bench the key for, or ``None`` if the key is not at fault.

    A malformed request or a model-side error will fail identically on every
    key, so rotating through the pool would just multiply the damage.
    """
    message = str(error).lower()
    status = _status_code(message)

    if any(marker in message for marker in _AUTH_MARKERS) or status in (401, 403):
        return AUTH_COOLDOWN_SECONDS
    if any(marker in message for marker in _BILLING_MARKERS):
        return BILLING_COOLDOWN_SECONDS
    if status == 429 or "resource_exhausted" in message:
        return RATE_LIMIT_COOLDOWN_SECONDS
    return None


def _status_code(message: str) -> int | None:
    match = re.search(r"\b(4\d{2}|5\d{2})\b", message)
    return int(match.group(1)) if match else None


@dataclass
class _PoolState:
    cooldowns: dict[str, float] = field(default_factory=dict)
    cursor: itertools.count = field(default_factory=lambda: itertools.count())


_states: dict[str, _PoolState] = {}
_lock = Lock()


def _state(provider: str) -> _PoolState:
    with _lock:
        return _states.setdefault(provider, _PoolState())


def ordered_keys(provider: str, keys: list[str]) -> list[str]:
    """Return ``keys`` in try order: healthy keys first, round-robined.

    Rotating the starting point spreads sustained load across accounts instead
    of hammering the first key until it rate-limits.
    """
    if len(keys) <= 1:
        return list(keys)

    state = _state(provider)
    now = time.monotonic()
    offset = next(state.cursor) % len(keys)
    rotated = keys[offset:] + keys[:offset]

    healthy = [key for key in rotated if state.cooldowns.get(key, 0.0) <= now]
    cooling = sorted(
        (key for key in rotated if state.cooldowns.get(key, 0.0) > now),
        key=lambda key: state.cooldowns[key],
    )
    return healthy + cooling


def mark_key_failure(provider: str, key: str, error: BaseException) -> float | None:
    """Bench ``key`` if ``error`` says the key itself is the problem."""
    cooldown = classify_key_failure(error)
    if cooldown is None:
        return None
    state = _state(provider)
    with _lock:
        state.cooldowns[key] = time.monotonic() + cooldown
    return cooldown


def mark_key_success(provider: str, key: str) -> None:
    """Clear a benched key that has started working again."""
    state = _state(provider)
    with _lock:
        state.cooldowns.pop(key, None)


def reset(provider: str | None = None) -> None:
    """Drop cooldown state. Test hook; also usable after a credential reload."""
    with _lock:
        if provider is None:
            _states.clear()
        else:
            _states.pop(provider, None)
