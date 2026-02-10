"""
Response caching service for identical API requests.

Caches completion responses in Redis to avoid redundant API calls.
"""

from .client import ResponseCache, get_response_cache
from .constants import (
    CACHE_PREFIX,
    DEFAULT_CACHE_TTL,
    FALLBACK_PREFIX,
    STALE_IF_ERROR_TTL,
)
from .models import CachedResponse, CacheStats

__all__ = [
    "CACHE_PREFIX",
    "DEFAULT_CACHE_TTL",
    "FALLBACK_PREFIX",
    "STALE_IF_ERROR_TTL",
    "CacheStats",
    "CachedResponse",
    "ResponseCache",
    "get_response_cache",
]
