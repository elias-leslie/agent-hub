"""Debug logging module for Agent Hub.

Simplified version that outputs to stderr for immediate visibility in logs.
The Hatchet worker captures these via journalctl.

Environment variables:
    DEBUG: Set to "true" to enable debug logging
    DEBUG_LEVEL: 1=basic flow, 2=detailed with timing, 3=verbose with payloads

Usage:
    from app.core.debug import debug, debug_async_timer

    debug("Processing request", request_id="abc123")

    async with debug_async_timer("LLM call"):
        response = await call_llm()
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

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
