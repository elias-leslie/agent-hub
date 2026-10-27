# Canonical source: synchronized across summitflow, agent-hub, portfolio-ai
"""Hatchet client singleton for workflow orchestration."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Coroutine
from datetime import timedelta
from functools import lru_cache, wraps
from typing import TYPE_CHECKING, Any, cast  # Any: __getattr__ return is inherently dynamic

from app.config import get_settings

if TYPE_CHECKING:
    from hatchet_sdk import Hatchet


logger = logging.getLogger(__name__)

# Hatchet injects hidden 60s execution / 5m schedule defaults when callers omit
# them. Keep one centralized, non-restrictive fallback here so long-running
# agentic workflows are not silently cancelled.
DEFAULT_TASK_SCHEDULE_TIMEOUT = timedelta(days=7)
DEFAULT_TASK_EXECUTION_TIMEOUT = timedelta(days=7)
_HATCHET_SHUTDOWN_404_GUARD_ATTR = "_hatchet_shutdown_404_guard"

PauseWorkerFn = Callable[..., Coroutine[Any, Any, Any]]


def _wrap_hatchet_shutdown_404_guard(
    pause_worker: PauseWorkerFn,
    *,
    not_found_exception: type[Exception],
) -> PauseWorkerFn:
    if getattr(pause_worker, _HATCHET_SHUTDOWN_404_GUARD_ATTR, False):
        return pause_worker

    @wraps(pause_worker)
    async def guarded_pause_worker(workers_client: Any, worker_id: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return await pause_worker(workers_client, worker_id, *args, **kwargs)
        except not_found_exception:
            logger.debug(
                "Hatchet worker %s already removed during shutdown pause; suppressing 404",
                worker_id,
            )
            return None

    setattr(guarded_pause_worker, _HATCHET_SHUTDOWN_404_GUARD_ATTR, True)
    return cast(PauseWorkerFn, guarded_pause_worker)


def _install_hatchet_shutdown_404_guard() -> None:
    """Treat shutdown-time Hatchet worker 404s as an already-complete pause.

    During SIGTERM/SIGQUIT shutdown races, Hatchet can evict the worker record
    before the graceful-shutdown pause (``Worker._pause_task_assignment()`` ->
    ``WorkersClient.aio_pause()``) reaches the REST update. That 404 is
    effectively "already paused / already gone" and should not surface as a
    shutdown error.
    """

    from hatchet_sdk.clients.rest.exceptions import NotFoundException
    from hatchet_sdk.features.workers import WorkersClient

    guarded_pause_worker = _wrap_hatchet_shutdown_404_guard(
        WorkersClient.aio_pause,
        not_found_exception=NotFoundException,
    )
    type.__setattr__(WorkersClient, "aio_pause", guarded_pause_worker)


def _prime_hatchet_env() -> None:
    settings = get_settings()
    for key, value in {
        "HATCHET_CLIENT_TOKEN": settings.hatchet_client_token,
        "HATCHET_CLIENT_HOST_PORT": settings.hatchet_client_host_port,
        "HATCHET_CLIENT_TLS_STRATEGY": settings.hatchet_client_tls_strategy,
    }.items():
        if value:
            os.environ.setdefault(key, value)


@lru_cache
def get_hatchet() -> Hatchet:
    """Get cached Hatchet client instance.

    Lazy initialization - only created on first call.
    Requires HATCHET_CLIENT_TOKEN env var.
    """
    _prime_hatchet_env()
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
