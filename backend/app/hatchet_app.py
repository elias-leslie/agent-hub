# Canonical source: synchronized across summitflow, agent-hub, portfolio-ai
"""Hatchet client singleton for workflow orchestration."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any  # Any: __getattr__ return is inherently dynamic

if TYPE_CHECKING:
    from hatchet_sdk import Hatchet


@lru_cache
def get_hatchet() -> Hatchet:
    """Get cached Hatchet client instance.

    Lazy initialization - only created on first call.
    Requires HATCHET_CLIENT_TOKEN env var.
    """
    from hatchet_sdk import Hatchet as HatchetClass

    return HatchetClass()


class _LazyHatchet:
    """Lazy proxy that defers Hatchet client creation until first attribute access.

    Allows workflow modules to import ``hatchet`` at module level for decorators
    without triggering client construction at import time.  The real
    ``Hatchet`` instance is only created when an attribute (e.g. ``.task()``,
    ``.worker()``) is first accessed.
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(get_hatchet(), name)


hatchet: Hatchet = _LazyHatchet()  # type: ignore[assignment]  # _LazyHatchet proxies Hatchet
