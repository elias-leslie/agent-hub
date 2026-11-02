"""Shared utility score helpers for memory usage analytics."""

from __future__ import annotations


def calculate_memory_utility_score(loaded_count: int, referenced_count: int) -> float:
    """Normalize memory utility to a 0..1 cited-vs-loaded ratio."""
    if loaded_count <= 0:
        return 0.0
    return min(1.0, max(0.0, referenced_count / loaded_count))
