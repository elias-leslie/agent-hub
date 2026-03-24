# Canonical source: synchronized across summitflow, agent-hub, portfolio-ai
"""Hatchet client singleton for workflow orchestration."""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from typing import TYPE_CHECKING, Any  # Any: __getattr__ return is inherently dynamic

if TYPE_CHECKING:
    from hatchet_sdk import Hatchet


# Hatchet injects hidden 60s execution / 5m schedule defaults when callers omit
# them. Keep one centralized, non-restrictive fallback here so long-running
# agentic workflows are not silently cancelled.
DEFAULT_TASK_SCHEDULE_TIMEOUT = timedelta(days=7)
DEFAULT_TASK_EXECUTION_TIMEOUT = timedelta(days=7)


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

    def task(self, *args: Any, **kwargs: Any) -> Any:
        """Apply centralized task timeout defaults before delegating to Hatchet."""
        effective_kwargs = dict(kwargs)
        effective_kwargs.setdefault("schedule_timeout", DEFAULT_TASK_SCHEDULE_TIMEOUT)
        effective_kwargs.setdefault("execution_timeout", DEFAULT_TASK_EXECUTION_TIMEOUT)
        return get_hatchet().task(*args, **effective_kwargs)

    def workflow(self, *args: Any, **kwargs: Any) -> Any:
        """Apply centralized workflow task defaults before delegating to Hatchet."""
        from hatchet_sdk.runnables.types import TaskDefaults

        effective_kwargs = dict(kwargs)
        task_defaults = effective_kwargs.get("task_defaults")
        merged = task_defaults.model_copy(deep=True) if isinstance(task_defaults, TaskDefaults) else TaskDefaults()
        if merged.schedule_timeout is None:
            merged.schedule_timeout = DEFAULT_TASK_SCHEDULE_TIMEOUT
        if merged.execution_timeout is None:
            merged.execution_timeout = DEFAULT_TASK_EXECUTION_TIMEOUT
        effective_kwargs["task_defaults"] = merged
        return get_hatchet().workflow(*args, **effective_kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(get_hatchet(), name)


hatchet: Hatchet = _LazyHatchet()  # type: ignore[assignment]  # _LazyHatchet proxies Hatchet
