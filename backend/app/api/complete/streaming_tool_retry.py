"""Retry logic for transient tool execution failures."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.tools.base import ToolCall, ToolHandler, ToolResult

logger = logging.getLogger(__name__)

_TOOL_MAX_RETRIES = 3
_TOOL_RETRY_BASE_DELAY = 2.0
_TOOL_RETRY_MAX_DELAY = 30.0

_TRANSIENT_ERROR_PATTERNS = (
    "429", "rate limit", "Rate limit",
    "503", "service unavailable", "Service Unavailable",
    "timeout", "timed out", "Timeout", "Timed out",
    "connection refused", "Connection refused",
    "connection reset", "Connection reset",
    "UNAVAILABLE", "RESOURCE_EXHAUSTED",
)


def is_transient_tool_error(error_content: str) -> bool:
    """Return True if error_content matches a known transient failure pattern."""
    return any(pattern in error_content for pattern in _TRANSIENT_ERROR_PATTERNS)


async def execute_tool_with_retry(
    handler: ToolHandler,
    tool_call: ToolCall,
    max_retries: int = _TOOL_MAX_RETRIES,
) -> ToolResult:
    """Execute a tool call with exponential-backoff retry for transient failures."""
    result = await handler.execute(tool_call)
    for attempt in range(1, max_retries):
        if not result.is_error or not is_transient_tool_error(result.content):
            return result
        base_delay = min(_TOOL_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _TOOL_RETRY_MAX_DELAY)
        delay = base_delay * (0.5 + random.random())
        logger.warning(
            "Transient tool error (attempt %d/%d), retrying in %.1fs: %s",
            attempt, max_retries, delay, result.content[:200],
        )
        await asyncio.sleep(delay)
        result = await handler.execute(tool_call)
    return result
