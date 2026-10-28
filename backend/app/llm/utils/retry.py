"""Shared re-send budget and backoff for interrupted model streams."""

from __future__ import annotations

import random

from app.config import settings

from ..types import StreamOptions


def retry_budget(options: StreamOptions | None) -> int:
    """Re-sends allowed after an interrupted request or turn."""

    if options is not None and options.max_retries is not None:
        return options.max_retries
    return settings.llm_stream_max_retries


def retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter for the zero-based ``attempt`` that just failed."""

    return min(8.0, 0.5 * 2**attempt) * random.uniform(0.8, 1.2)
