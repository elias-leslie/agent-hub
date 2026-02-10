"""Data models for response caching."""

from dataclasses import dataclass
from typing import Any


@dataclass
class CacheStats:
    """Cache statistics."""

    hits: int = 0
    misses: int = 0
    total_requests: int = 0
    fallback_hits: int = 0
    fallback_misses: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    @property
    def fallback_usage(self) -> int:
        """Total fallback responses served."""
        return self.fallback_hits


@dataclass
class CachedResponse:
    """A cached response with metadata."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None
    cached_at: str
    cache_key: str
    is_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "content": self.content,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "finish_reason": self.finish_reason,
            "cached_at": self.cached_at,
            "cache_key": self.cache_key,
            "is_fallback": self.is_fallback,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CachedResponse":
        """Create from dictionary."""
        return cls(
            content=data["content"],
            model=data["model"],
            provider=data["provider"],
            input_tokens=data["input_tokens"],
            output_tokens=data["output_tokens"],
            finish_reason=data.get("finish_reason"),
            cached_at=data["cached_at"],
            cache_key=data["cache_key"],
            is_fallback=data.get("is_fallback", False),
        )
