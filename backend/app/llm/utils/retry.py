"""The one re-send policy for model requests: budget, backoff and which errors count.

A model call ends only on a definite death signal (connection reset or closed, HTTP error,
``response.failed``/``error`` event, EOF before completion). Silence and elapsed time never end one.
Providers tag such a death as an ``interrupted`` outcome; the layer in ``tool_loop.run_turn`` is the only
place that re-sends, so the budget is spent once and every re-send is visible as a ``TurnRetry``.
"""

from __future__ import annotations

import random

import httpx

from app.config import settings

from ..types import StreamOptions
from .outcomes import ProviderOutcome, record_outcome

# SDK connection/timeout error classes that wrap a dropped or refused connection.
_CONNECTION_ERROR_NAMES = frozenset({"APIConnectionError", "APITimeoutError"})


def retry_budget(options: StreamOptions | None) -> int:
    """Re-sends allowed after an interrupted request or turn."""

    if options is not None and options.max_retries is not None:
        return options.max_retries
    return settings.llm_stream_max_retries


def retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter for the zero-based ``attempt`` that just failed."""

    base = min(settings.llm_retry_max_delay_s, settings.llm_retry_base_delay_s * 2**attempt)
    jitter = settings.llm_retry_jitter
    return min(settings.llm_retry_max_delay_s, base * random.uniform(1 - jitter, 1 + jitter))


def is_transient_failure(exc: BaseException) -> bool:
    """True for a definite transport or server failure that a re-send can fix.

    A dropped, refused or reset connection, or an HTTP 5xx. A 429 is a rate limit (cooldown and fallback
    handle it), 4xx is the request's own fault, and a refusal or usage limit is never transient.
    """

    if isinstance(exc, httpx.TransportError | ConnectionError):
        return True
    if any(cls.__name__ in _CONNECTION_ERROR_NAMES for cls in type(exc).__mro__):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return isinstance(status, int) and not isinstance(status, bool) and 500 <= status < 600


def tag_if_transient(message: object, exc: BaseException, requested_model: str) -> None:
    """Mark a failed ``message`` as ``interrupted`` when ``exc`` is a transient transport or server failure."""

    if is_transient_failure(exc):
        record_outcome(
            message,
            ProviderOutcome(kind="interrupted", requested_model=requested_model, explanation=str(exc) or type(exc).__name__),
        )
