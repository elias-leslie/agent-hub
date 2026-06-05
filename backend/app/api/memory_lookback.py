"""Helpers for parsing compact memory analytics lookback ranges."""

from __future__ import annotations

from datetime import timedelta

MAX_MEMORY_LOOKBACK_DAYS = 90


def parse_memory_lookback(lookback: str | None, fallback_days: int) -> tuple[timedelta, str]:
    """Return a lookback delta and canonical label.

    Supports ``1h``, ``1d``, ``7d``, ``14d``, and ``30d``.
    Falls back to ``fallback_days`` when no explicit lookback is provided.
    """
    if not lookback:
        return timedelta(days=fallback_days), f"{fallback_days}d"

    normalized = lookback.strip().lower()
    if normalized == "1h":
        return timedelta(hours=1), normalized
    if normalized.endswith("d") and normalized[:-1].isdigit():
        days = int(normalized[:-1])
        if days < 1 or days > MAX_MEMORY_LOOKBACK_DAYS:
            msg = f"Invalid lookback value: {lookback}"
            raise ValueError(msg)
        return timedelta(days=days), normalized

    msg = f"Invalid lookback value: {lookback}"
    raise ValueError(msg)
