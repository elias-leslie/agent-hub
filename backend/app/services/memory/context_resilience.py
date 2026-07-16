"""Shared retry and fail-closed helpers for memory/context injection."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

DEFAULT_MEMORY_ATTEMPTS = 3
DEFAULT_MEMORY_INITIAL_BACKOFF_SECONDS = 0.25
DEFAULT_MEMORY_MAX_BACKOFF_SECONDS = 1.0

_T = TypeVar("_T")
logger = logging.getLogger(__name__)


class CanonicalContextInjectionFailed(RuntimeError):
    """Raised before model execution when canonical context is unavailable."""

    def __init__(self, notice: str) -> None:
        self.notice = notice
        super().__init__(notice)


@dataclass(slots=True)
class MemoryFailureDetails:
    """Normalized failure details for fail-closed memory delivery."""

    operation: str
    attempts: int
    error_type: str
    error_message: str
    latency_ms: int


def _truncate_error_message(message: str, limit: int = 240) -> str:
    cleaned = " ".join((message or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def build_memory_failure_notice(
    failure: MemoryFailureDetails,
    *,
    consumer_profile: str | None = None,
    project_id: str | None = None,
) -> str:
    """Return the minimal fail-closed instruction block for all agent types."""
    lines = [
        "<memory-system-status>",
        "**CRITICAL:** Agent Hub memory/context injection failed.",
        "Mandates, guardrails, project index, tool capabilities, and continuity context may be missing.",
        "Stop substantive work immediately and notify the operator/user that memory injection failed.",
        "Do not make code changes, run migrations, execute destructive commands, or provide a normal task answer until memory is restored.",
        "Ask the operator to run `st memory status` and restore the memory system before resuming.",
        f"Failure: {failure.error_type}: {failure.error_message}",
        f"Attempts: {failure.attempts}",
        f"Operation: {failure.operation}",
    ]
    if consumer_profile:
        lines.append(f"Consumer profile: {consumer_profile}")
    if project_id:
        lines.append(f"Project: {project_id}")
    lines.append("</memory-system-status>")
    return "\n".join(lines)


def build_unexpected_context_failure_notice(
    error: Exception,
    *,
    operation: str,
    consumer_profile: str | None = None,
    project_id: str | None = None,
) -> str:
    """Render an unexpected wrapper failure as model-visible stop context."""
    return build_memory_failure_notice(
        MemoryFailureDetails(
            operation=operation,
            attempts=1,
            error_type=type(error).__name__,
            error_message=_truncate_error_message(str(error) or "unknown error"),
            latency_ms=0,
        ),
        consumer_profile=consumer_profile,
        project_id=project_id,
    )


def require_successful_context_injection(context: object) -> None:
    """Abort a workload before its model call when delivery failed closed."""
    debug_info = getattr(context, "debug_info", {})
    if not isinstance(debug_info, dict) or not debug_info.get("memory_system_failed"):
        return
    notice = str(
        debug_info.get("failure_notice")
        or "Agent Hub canonical context injection failed; stop before model execution."
    )
    raise CanonicalContextInjectionFailed(notice)


async def run_with_memory_retries(
    operation: Callable[[], Awaitable[_T]],
    *,
    operation_name: str,
    attempts: int = DEFAULT_MEMORY_ATTEMPTS,
    initial_backoff_seconds: float = DEFAULT_MEMORY_INITIAL_BACKOFF_SECONDS,
    max_backoff_seconds: float = DEFAULT_MEMORY_MAX_BACKOFF_SECONDS,
) -> tuple[_T | None, MemoryFailureDetails | None, int, int]:
    """Run one memory operation with bounded retries and no hard timeout."""
    started = time.monotonic()
    last_error: Exception | None = None

    for attempt in range(1, max(attempts, 1) + 1):
        try:
            result = await operation()
            latency_ms = int((time.monotonic() - started) * 1000)
            return result, None, attempt, latency_ms
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - exercised via callers
            last_error = exc
            latency_ms = int((time.monotonic() - started) * 1000)
            if attempt >= max(attempts, 1):
                failure = MemoryFailureDetails(
                    operation=operation_name,
                    attempts=attempt,
                    error_type=type(exc).__name__,
                    error_message=_truncate_error_message(str(exc) or "unknown error"),
                    latency_ms=latency_ms,
                )
                logger.error(
                    "Memory operation failed after %d attempt(s): operation=%s error=%s latency=%dms",
                    attempt,
                    operation_name,
                    failure.error_type,
                    latency_ms,
                )
                return None, failure, attempt, latency_ms

            delay = min(initial_backoff_seconds * (2 ** (attempt - 1)), max_backoff_seconds)
            logger.warning(
                "Memory operation failed on attempt %d/%d: operation=%s error=%s retry_in=%.2fs",
                attempt,
                attempts,
                operation_name,
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)

    # Unreachable in practice, but keeps the type checker satisfied.
    latency_ms = int((time.monotonic() - started) * 1000)
    failure = MemoryFailureDetails(
        operation=operation_name,
        attempts=max(attempts, 1),
        error_type=type(last_error).__name__ if last_error else "RuntimeError",
        error_message=_truncate_error_message(str(last_error) if last_error else "unknown error"),
        latency_ms=latency_ms,
    )
    return None, failure, max(attempts, 1), latency_ms
