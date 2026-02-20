"""Provider detection and adapter management for completions.

Delegates to the unified adapter registry.
"""

from app.adapters.base import ProviderAdapter
from app.adapters.registry import get_adapter as registry_get_adapter


def get_adapter(provider: str) -> ProviderAdapter:
    """Get cached adapter instance."""
    return registry_get_adapter(provider)
