from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from hatchet_sdk.features.workers import WorkersClient
from hatchet_sdk.runnables.types import TaskDefaults

from app.hatchet_app import (
    _HATCHET_SHUTDOWN_404_GUARD_ATTR,
    DEFAULT_TASK_EXECUTION_TIMEOUT,
    DEFAULT_TASK_SCHEDULE_TIMEOUT,
    _LazyHatchet,
    _wrap_hatchet_shutdown_404_guard,
)


def test_task_wrapper_injects_nonrestrictive_defaults(monkeypatch) -> None:
    mock_hatchet = MagicMock()
    sentinel = object()
    mock_hatchet.task.return_value = sentinel
    monkeypatch.setattr("app.hatchet_app.get_hatchet", lambda: mock_hatchet)

    result = _LazyHatchet().task(name="example")

    assert result is sentinel
    kwargs = mock_hatchet.task.call_args.kwargs
    assert kwargs["schedule_timeout"] == DEFAULT_TASK_SCHEDULE_TIMEOUT
    assert kwargs["execution_timeout"] == DEFAULT_TASK_EXECUTION_TIMEOUT


def test_task_wrapper_preserves_explicit_timeouts(monkeypatch) -> None:
    mock_hatchet = MagicMock()
    monkeypatch.setattr("app.hatchet_app.get_hatchet", lambda: mock_hatchet)

    _LazyHatchet().task(
        name="example",
        schedule_timeout=timedelta(minutes=2),
        execution_timeout=timedelta(minutes=3),
    )

    kwargs = mock_hatchet.task.call_args.kwargs
    assert kwargs["schedule_timeout"] == timedelta(minutes=2)
    assert kwargs["execution_timeout"] == timedelta(minutes=3)


def test_workflow_wrapper_injects_task_defaults(monkeypatch) -> None:
    mock_hatchet = MagicMock()
    sentinel = object()
    mock_hatchet.workflow.return_value = sentinel
    monkeypatch.setattr("app.hatchet_app.get_hatchet", lambda: mock_hatchet)

    result = _LazyHatchet().workflow(name="example")

    assert result is sentinel
    task_defaults = mock_hatchet.workflow.call_args.kwargs["task_defaults"]
    assert isinstance(task_defaults, TaskDefaults)
    assert task_defaults.schedule_timeout == DEFAULT_TASK_SCHEDULE_TIMEOUT
    assert task_defaults.execution_timeout == DEFAULT_TASK_EXECUTION_TIMEOUT


def test_get_hatchet_primes_sdk_env_from_settings(monkeypatch) -> None:
    for key in ("HATCHET_CLIENT_TOKEN", "HATCHET_CLIENT_HOST_PORT", "HATCHET_CLIENT_TLS_STRATEGY"):
        monkeypatch.delenv(key, raising=False)

    class StubSettings:
        hatchet_client_token = "token-from-settings"
        hatchet_client_host_port = "hatchet:7070"
        hatchet_client_tls_strategy = "none"

    mock_hatchet_cls = MagicMock(return_value="hatchet-client")

    monkeypatch.setattr("app.hatchet_app.get_settings", lambda: StubSettings())
    monkeypatch.setattr("hatchet_sdk.Hatchet", mock_hatchet_cls)

    from app.hatchet_app import get_hatchet

    get_hatchet.cache_clear()
    try:
        result = get_hatchet()
    finally:
        get_hatchet.cache_clear()

    assert result == "hatchet-client"
    assert os.environ["HATCHET_CLIENT_TOKEN"] == "token-from-settings"
    assert os.environ["HATCHET_CLIENT_HOST_PORT"] == "hatchet:7070"
    assert os.environ["HATCHET_CLIENT_TLS_STRATEGY"] == "none"
    mock_hatchet_cls.assert_called_once_with()


def test_shutdown_guard_swallows_worker_not_found() -> None:
    class FakeNotFound(Exception):
        pass

    call_log: list[str] = []

    async def raise_not_found(_workers_client: object, worker_id: str) -> None:
        call_log.append(worker_id)
        raise FakeNotFound()

    guarded = _wrap_hatchet_shutdown_404_guard(raise_not_found, not_found_exception=FakeNotFound)

    assert asyncio.run(guarded(SimpleNamespace(), "worker-123")) is None
    assert call_log == ["worker-123"]


def test_shutdown_guard_preserves_unexpected_errors() -> None:
    class FakeNotFound(Exception):
        pass

    async def raise_unexpected(_workers_client: object, _worker_id: str) -> None:
        raise RuntimeError("boom")

    guarded = _wrap_hatchet_shutdown_404_guard(raise_unexpected, not_found_exception=FakeNotFound)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(guarded(SimpleNamespace(), "worker-123"))


def test_shutdown_guard_is_idempotent_and_passes_results() -> None:
    class FakeNotFound(Exception):
        pass

    async def pause_ok(_workers_client: object, worker_id: str) -> str:
        return f"paused:{worker_id}"

    guarded = _wrap_hatchet_shutdown_404_guard(pause_ok, not_found_exception=FakeNotFound)

    assert asyncio.run(guarded(SimpleNamespace(), "worker-123")) == "paused:worker-123"
    assert _wrap_hatchet_shutdown_404_guard(guarded, not_found_exception=FakeNotFound) is guarded


def test_worker_runtime_import_installs_guard_on_sdk_worker_pause() -> None:
    import app.worker_runtime  # noqa: F401  # the worker process installs the guard by importing this

    assert getattr(WorkersClient.aio_pause, _HATCHET_SHUTDOWN_404_GUARD_ATTR, False) is True
