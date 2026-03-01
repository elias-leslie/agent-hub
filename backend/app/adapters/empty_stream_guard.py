"""Guard against empty/stalled adapter streams.

Retries the stream factory once if no content events arrive within the threshold.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


async def guard_empty_stream(
    stream_factory: Any,
    threshold_seconds: float = 30.0,
    max_retries: int = 1,
) -> AsyncIterator[Any]:
    """Yield events from a stream, retrying if no content arrives within threshold.

    Args:
        stream_factory: An async callable that returns an async iterator of stream events.
        threshold_seconds: Max seconds to wait for first content event before retrying.
        max_retries: Number of retry attempts (default 1).

    Yields:
        Stream events from the adapter.

    Raises:
        asyncio.TimeoutError: If all retries exhaust without receiving content.
    """
    for attempt in range(max_retries + 1):
        got_content = False
        timed_out = False

        async def _iter_with_watchdog() -> AsyncIterator[Any]:
            nonlocal got_content, timed_out
            deadline = asyncio.get_event_loop().time() + threshold_seconds

            async for event in await stream_factory():
                event_type = getattr(event, "type", None)
                if event_type == "content":
                    got_content = True
                if not got_content and asyncio.get_event_loop().time() > deadline:
                    timed_out = True
                    return
                yield event

        async for event in _iter_with_watchdog():
            yield event

        if got_content or not timed_out:
            return

        if attempt < max_retries:
            logger.warning(
                "Empty stream detected (no content in %.0fs), retrying (attempt %d/%d)",
                threshold_seconds,
                attempt + 1,
                max_retries,
            )
        else:
            raise TimeoutError(
                f"Stream produced no content after {threshold_seconds}s "
                f"({max_retries + 1} attempts)"
            )
