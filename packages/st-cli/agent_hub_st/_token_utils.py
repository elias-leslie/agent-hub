"""Small presentation-only token estimate used by prompt listings."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Estimate token count using the established four-characters heuristic."""
    return len(text) // 4

