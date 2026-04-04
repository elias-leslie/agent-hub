from __future__ import annotations

import os
from datetime import timedelta
from unittest.mock import MagicMock

from hatchet_sdk.runnables.types import TaskDefaults

from app.hatchet_app import (
    DEFAULT_TASK_EXECUTION_TIMEOUT,
    DEFAULT_TASK_SCHEDULE_TIMEOUT,
    _LazyHatchet,
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
