"""Debug logging module for Agent Hub.

Simplified version that outputs to stderr for immediate visibility in logs.
SummitFlow's Celery worker captures these via journalctl.

Environment variables:
    DEBUG: Set to "true" to enable debug logging
    DEBUG_LEVEL: 1=basic flow, 2=detailed with timing, 3=verbose with payloads

Usage:
    from app.core.debug import debug, debug_timer, is_debug_enabled

    if is_debug_enabled():
        debug("Processing request", request_id="abc123")

    with debug_timer("LLM call"):
        response = call_llm()
"""

from __future__ import annotations

import functools
import os
import sys
import time
from collections.abc import AsyncGenerator, Callable, Coroutine, Generator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from typing import Any, ParamSpec, TypeVar, overload

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")

_DEBUG = os.environ.get("DEBUG", "").lower() == "true"
_DEBUG_LEVEL = int(os.environ.get("DEBUG_LEVEL", "1"))


def is_debug_enabled(level: int = 1) -> bool:
    """Check if debug logging is enabled for the given level."""
    return _DEBUG and level <= _DEBUG_LEVEL


def _emit_stderr(
    message: str,
    function_name: str | None = None,
    elapsed_ms: float | None = None,
    **attributes: Any,
) -> None:
    """Emit to stderr for immediate visibility in logs."""
    timestamp = datetime.now(UTC).strftime("%H:%M:%S.%f")[:-3]
    parts = [f"[DEBUG {timestamp}]"]
    if function_name:
        parts.append(f"[{function_name}]")
    parts.append(message)
    if elapsed_ms is not None:
        parts.append(f"({elapsed_ms:.1f}ms)")
    if attributes:
        extras = " ".join(f"{k}={v}" for k, v in attributes.items() if v is not None)
        if extras:
            parts.append(f"| {extras}")
    print(" ".join(parts), file=sys.stderr)


def debug(message: str, **kwargs: Any) -> None:
    """Emit a basic debug message (level 1)."""
    if not is_debug_enabled(1):
        return
    _emit_stderr(message, **kwargs)


def debug_detailed(message: str, **kwargs: Any) -> None:
    """Emit a detailed debug message (level 2)."""
    if not is_debug_enabled(2):
        return
    _emit_stderr(message, **kwargs)


def debug_verbose(message: str, **kwargs: Any) -> None:
    """Emit a verbose debug message (level 3)."""
    if not is_debug_enabled(3):
        return
    _emit_stderr(message, **kwargs)


@contextmanager
def debug_timer(operation: str, **kwargs: Any) -> Generator[None]:
    """Context manager for timing synchronous operations (level 2)."""
    if not is_debug_enabled(2):
        yield
        return

    start = time.perf_counter()
    _emit_stderr(f"-> {operation}")
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        _emit_stderr(f"<- {operation}", elapsed_ms=elapsed_ms, **kwargs)


@asynccontextmanager
async def debug_async_timer(operation: str, **kwargs: Any) -> AsyncGenerator[None]:
    """Context manager for timing async operations (level 2)."""
    if not is_debug_enabled(2):
        yield
        return

    start = time.perf_counter()
    _emit_stderr(f"-> {operation}")
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        _emit_stderr(f"<- {operation}", elapsed_ms=elapsed_ms, **kwargs)


def debug_timer_decorator(
    func: Callable[P, R] | None = None,
    *,
    operation: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]] | Callable[P, R]:
    """Decorator for timing functions (level 2)."""

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        op_name = operation or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if not is_debug_enabled(2):
                return fn(*args, **kwargs)

            start = time.perf_counter()
            _emit_stderr(f"-> {op_name}", function_name=fn.__name__)
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                _emit_stderr(f"<- {op_name}", function_name=fn.__name__, elapsed_ms=elapsed_ms)

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


@overload
def debug_async_timer_decorator(
    func: Callable[P, Coroutine[Any, Any, T]],
    *,
    operation: str | None = ...,
) -> Callable[P, Coroutine[Any, Any, T]]: ...


@overload
def debug_async_timer_decorator(
    func: None = ...,
    *,
    operation: str | None = ...,
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]: ...


def debug_async_timer_decorator(
    func: Callable[P, Coroutine[Any, Any, T]] | None = None,
    *,
    operation: str | None = None,
) -> (
    Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]
    | Callable[P, Coroutine[Any, Any, T]]
):
    """Decorator for timing async functions (level 2)."""

    def decorator(
        fn: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        op_name = operation or fn.__name__

        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            if not is_debug_enabled(2):
                return await fn(*args, **kwargs)

            start = time.perf_counter()
            _emit_stderr(f"-> {op_name}", function_name=fn.__name__)
            try:
                return await fn(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                _emit_stderr(f"<- {op_name}", function_name=fn.__name__, elapsed_ms=elapsed_ms)

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator
