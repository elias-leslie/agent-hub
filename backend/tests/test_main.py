from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import _startup


def _mock_async_session(mock_db: AsyncMock):
    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session


@pytest.mark.asyncio
async def test_startup_reconciles_registered_project_access(caplog: pytest.LogCaptureFixture) -> None:
    mock_db = AsyncMock()
    session_factory = _mock_async_session(mock_db)
    credential_manager = MagicMock()
    credential_manager.load_with_retry = AsyncMock(return_value=2)
    prober = SimpleNamespace(_providers=["claude", "gemini"])

    with caplog.at_level(logging.INFO, logger="app.main"), patch(
        "app.main.init_telemetry"
    ), patch(
        "app.main.get_credential_manager", return_value=credential_manager
    ), patch(
        "app.main.start_usage_tracker", new_callable=AsyncMock
    ) as mock_start_usage_tracker, patch(
        "app.main.normalize_legacy_scope_rows", new_callable=AsyncMock, return_value={}
    ), patch(
        "app.main.async_session", session_factory
    ), patch(
        "app.main.reconcile_registered_project_access",
        new_callable=AsyncMock,
        return_value=["client-1", "client-2"],
    ) as mock_reconcile, patch(
        "app.constants.projects.refresh_project_ids_cache",
        new_callable=AsyncMock,
        return_value=["agent-hub"],
    ), patch(
        "app.services.health_prober.init_health_prober", return_value=prober
    ) as mock_init_health_prober:
        await _startup()

    credential_manager.load_with_retry.assert_awaited_once_with(session_factory)
    mock_start_usage_tracker.assert_awaited_once()
    mock_reconcile.assert_awaited_once_with(mock_db)
    mock_init_health_prober.assert_called_once_with()
    assert (
        "Reconciled registered project access for 2 SummitFlow-owned client(s): "
        "client-1, client-2"
    ) in caplog.text


@pytest.mark.asyncio
async def test_startup_logs_registered_access_reconciliation_failure_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_db = AsyncMock()
    session_factory = _mock_async_session(mock_db)
    credential_manager = MagicMock()
    credential_manager.load_with_retry = AsyncMock(return_value=2)
    prober = SimpleNamespace(_providers=["claude"])

    with caplog.at_level(logging.INFO, logger="app.main"), patch(
        "app.main.init_telemetry"
    ), patch(
        "app.main.get_credential_manager", return_value=credential_manager
    ), patch(
        "app.main.start_usage_tracker", new_callable=AsyncMock
    ), patch(
        "app.main.normalize_legacy_scope_rows", new_callable=AsyncMock, return_value={}
    ), patch(
        "app.main.async_session", session_factory
    ), patch(
        "app.main.reconcile_registered_project_access",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ) as mock_reconcile, patch(
        "app.constants.projects.refresh_project_ids_cache",
        new_callable=AsyncMock,
        return_value=["agent-hub"],
    ), patch(
        "app.services.health_prober.init_health_prober", return_value=prober
    ) as mock_init_health_prober:
        await _startup()

    credential_manager.load_with_retry.assert_awaited_once_with(session_factory)
    mock_reconcile.assert_awaited_once_with(mock_db)
    mock_init_health_prober.assert_called_once_with()
    assert "Failed registered project access reconciliation at startup: boom" in caplog.text
    assert "Provider health tracker initialized for 1 providers" in caplog.text
