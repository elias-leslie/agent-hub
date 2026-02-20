"""Adapter factory and cache for completion API.

Delegates to the unified adapter registry. Kept as a thin re-export
for backward compatibility with existing import sites.
"""

from __future__ import annotations

from app.adapters.base import ProviderAdapter
from app.adapters.registry import (
    clear_cache as clear_adapter_cache,
)
from app.adapters.registry import (
    get_adapter,
)
from app.adapters.registry import (
    invalidate as invalidate_adapter,
)

__all__ = [
    "ProviderAdapter",
    "clear_adapter_cache",
    "get_adapter",
    "invalidate_adapter",
]
