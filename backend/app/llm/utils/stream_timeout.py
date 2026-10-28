"""The one transport read bound every model transport uses: ``settings.llm_stream_read_timeout_s``.

It is silence on the wire (no bytes at all; SSE keepalives are bytes), never elapsed time: a model that keeps
the connection talking is never cut off. When it fires the request ends as a retryable ``interrupted`` outcome whose
reason names the bound, so the per-request ``model_request`` record and the retry log show it.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# How long a connection may take to open; a dead host is told apart from a slow model by this, not by the read bound.
CONNECT_TIMEOUT_S = 30.0
IDLE_TIMEOUT_PREFIX = "stream_idle_timeout"


def stream_timeout_s(timeout_ms: int | None = None) -> float:
    """The read bound in seconds: the configured setting, or the request's own ``timeout_ms`` when it set one."""

    return settings.llm_stream_read_timeout_s if timeout_ms is None else timeout_ms / 1000


def stream_timeout(timeout_ms: int | None = None) -> httpx.Timeout:
    """The ``httpx`` timeout for a model connection, with the read bound set explicitly (no SDK default)."""

    seconds = stream_timeout_s(timeout_ms)
    return httpx.Timeout(seconds, connect=min(CONNECT_TIMEOUT_S, seconds))


def is_timeout(exc: BaseException) -> bool:
    """Whether ``exc`` is an httpx or SDK timeout (the SDKs wrap httpx's in an ``APITimeoutError``)."""

    return isinstance(exc, httpx.TimeoutException) or any(cls.__name__ == "APITimeoutError" for cls in type(exc).__mro__)


def timeout_reason(exc: BaseException, timeout_ms: int | None = None) -> str | None:
    """A reason naming the firing bound when ``exc`` is a transport timeout, else None."""

    if not is_timeout(exc):
        return None
    seconds = stream_timeout_s(timeout_ms)
    kind = type(exc.__cause__ or exc).__name__
    return f"{IDLE_TIMEOUT_PREFIX}: no bytes from the model connection for {seconds:g}s ({kind}); the request is re-sent"


def note_timeout(exc: BaseException, model_id: str, timeout_ms: int | None = None) -> str | None:
    """``timeout_reason`` plus a warning log line, so every firing leaves a record."""

    reason = timeout_reason(exc, timeout_ms)
    if reason is not None:
        logger.warning("model=%s %s", model_id, reason)
    return reason
