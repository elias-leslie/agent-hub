"""Shared utility score helpers for memory usage analytics."""

from __future__ import annotations

from sqlalchemy import Float, cast, func


def calculate_memory_utility_score(loaded_count: int, referenced_count: int) -> float:
    """Normalize memory utility to a 0..1 cited-vs-loaded ratio."""
    if loaded_count <= 0:
        return 0.0
    return min(1.0, max(0.0, referenced_count / loaded_count))


def utility_score_sql_expr(loaded_count_col, referenced_count_col):
    """Return SQL expression matching calculate_memory_utility_score()."""
    loaded = func.nullif(loaded_count_col, 0)
    ratio = cast(referenced_count_col, Float) / loaded
    return func.coalesce(func.least(1.0, ratio), 0.0)
