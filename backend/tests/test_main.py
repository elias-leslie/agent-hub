from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import _startup
from app.services.compactness_policy import DEFAULTS as COMPACTNESS_DEFAULTS


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

    with caplog.at_level(logging.INFO, logger="app.main"), patch(
        "app.main.init_telemetry"
    ), patch(
        "app.main.get_credential_manager", return_value=credential_manager
    ), patch(
        "app.main.load_env_credentials_into_cache",
        return_value=["openai:api_key"],
    ), patch(
        "app.main.start_usage_tracker", new_callable=AsyncMock
    ) as mock_start_usage_tracker, patch(
        "app.main.normalize_legacy_scope_rows", new_callable=AsyncMock, return_value={}
    ), patch(
        "app.main.async_session", session_factory
    ), patch(
        "app.main.bootstrap_default_agents",
        new_callable=AsyncMock,
        return_value=39,
    ) as mock_bootstrap_default_agents, patch(
        "app.main.reconcile_agent_models_to_available_providers",
        new_callable=AsyncMock,
        return_value=["adaptive-routing:42"],
    ) as mock_reconcile_agent_models, patch(
        "app.main.reconcile_first_party_clients",
        new_callable=AsyncMock,
        return_value=["portfolio-client"],
    ) as mock_reconcile_first_party, patch(
        "app.main.reconcile_registered_project_access",
        new_callable=AsyncMock,
        return_value=["client-1", "client-2"],
    ) as mock_reconcile, patch(
        "app.constants.projects.refresh_project_ids_cache",
        new_callable=AsyncMock,
        return_value=["agent-hub"],
    ), patch(
        "app.services.compactness_policy.load_policy_from_db",
        new_callable=AsyncMock,
        return_value=COMPACTNESS_DEFAULTS,
    ):
        await _startup()

    credential_manager.load_with_retry.assert_awaited_once_with(session_factory)
    mock_start_usage_tracker.assert_awaited_once()
    mock_bootstrap_default_agents.assert_awaited_once_with(mock_db)
    mock_reconcile_agent_models.assert_awaited_once_with(mock_db)
    mock_reconcile_first_party.assert_awaited_once_with(mock_db)
    mock_reconcile.assert_awaited_once_with(mock_db)
    assert "Loaded 1 env-backed credential override(s): openai:api_key" in caplog.text
    assert "Seeded 39 default agent(s) for a fresh database" in caplog.text
    assert "Seeded/refreshed adaptive routing metadata: adaptive-routing:42" in caplog.text
    assert "Reconciled 1 first-party client registration(s): portfolio-client" in caplog.text
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

    with caplog.at_level(logging.INFO, logger="app.main"), patch(
        "app.main.init_telemetry"
    ), patch(
        "app.main.get_credential_manager", return_value=credential_manager
    ), patch(
        "app.main.load_env_credentials_into_cache",
        return_value=[],
    ), patch(
        "app.main.start_usage_tracker", new_callable=AsyncMock
    ), patch(
        "app.main.normalize_legacy_scope_rows", new_callable=AsyncMock, return_value={}
    ), patch(
        "app.main.async_session", session_factory
    ), patch(
        "app.main.bootstrap_default_agents",
        new_callable=AsyncMock,
        side_effect=RuntimeError("seed boom"),
    ) as mock_bootstrap_default_agents, patch(
        "app.main.reconcile_agent_models_to_available_providers",
        new_callable=AsyncMock,
        side_effect=RuntimeError("model boom"),
    ) as mock_reconcile_agent_models, patch(
        "app.main.reconcile_first_party_clients",
        new_callable=AsyncMock,
        side_effect=RuntimeError("first-party boom"),
    ) as mock_reconcile_first_party, patch(
        "app.main.reconcile_registered_project_access",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ) as mock_reconcile, patch(
        "app.constants.projects.refresh_project_ids_cache",
        new_callable=AsyncMock,
        return_value=["agent-hub"],
    ), patch(
        "app.services.compactness_policy.load_policy_from_db",
        new_callable=AsyncMock,
        return_value=COMPACTNESS_DEFAULTS,
    ):
        await _startup()

    credential_manager.load_with_retry.assert_awaited_once_with(session_factory)
    mock_bootstrap_default_agents.assert_awaited_once_with(mock_db)
    mock_reconcile_agent_models.assert_awaited_once_with(mock_db)
    mock_reconcile_first_party.assert_awaited_once_with(mock_db)
    mock_reconcile.assert_awaited_once_with(mock_db)
    assert "No env-backed credential overrides configured" in caplog.text
    assert "Failed default agent bootstrap at startup: seed boom" in caplog.text
    assert "Failed adaptive routing reconciliation at startup: model boom" in caplog.text
    assert "Failed first-party client reconciliation at startup: first-party boom" in caplog.text
    assert "Failed registered project access reconciliation at startup: boom" in caplog.text
    assert "Provider health tracker disabled" in caplog.text
