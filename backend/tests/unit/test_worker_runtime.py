from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker_runtime import (
    AGENT_WORKFLOWS,
    ALL_WORKFLOWS,
    OPS_WORKFLOWS,
    init_worker_credentials,
)
from app.workflows.completion import completion_task
from app.workflows.model_sync import model_enrichment_sync_task
from app.workflows.observation import observation_processing_task
from app.workflows.persona_heartbeat import persona_heartbeat_task
from app.workflows.persona_scheduler import persona_scheduler_task
from app.workflows.persona_wake import agent_wake_task
from app.workflows.scheduled import (
    data_retention_task,
    feedback_cleanup_task,
    memory_cleanup_task,
    memory_governance_task,
    session_cleanup_task,
    tier_optimizer_task,
)
from app.workflows.session_reaper import session_reaper_task
from app.workflows.summary import session_summary_task
from app.workflows.webhooks import webhook_delivery_task


def test_agent_workflows_match_long_lived_agent_runtime() -> None:
    assert (
        completion_task,
        persona_heartbeat_task,
        agent_wake_task,
    ) == AGENT_WORKFLOWS


def test_ops_workflows_match_maintenance_runtime() -> None:
    assert (
        persona_scheduler_task,
        session_cleanup_task,
        tier_optimizer_task,
        memory_cleanup_task,
        memory_governance_task,
        feedback_cleanup_task,
        data_retention_task,
        webhook_delivery_task,
        session_summary_task,
        observation_processing_task,
        model_enrichment_sync_task,
        session_reaper_task,
    ) == OPS_WORKFLOWS


def test_all_workflows_combine_split_workers_without_duplicates() -> None:
    assert ALL_WORKFLOWS == OPS_WORKFLOWS + AGENT_WORKFLOWS
    assert len(ALL_WORKFLOWS) == len(set(ALL_WORKFLOWS))


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog_unavailable", [False, True])
async def test_worker_loads_database_model_metadata_before_starting(
    catalog_unavailable: bool,
) -> None:
    engine = MagicMock(dispose=AsyncMock())
    credential_manager = MagicMock(load_with_retry=AsyncMock(return_value=2))
    session = AsyncMock()
    session.__aenter__.return_value = session
    refresh = AsyncMock(
        side_effect=RuntimeError("catalog unavailable") if catalog_unavailable else None,
    )
    with (
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=engine),
        patch("sqlalchemy.ext.asyncio.AsyncSession", return_value=session),
        patch(
            "app.services.credential_manager.get_credential_manager",
            return_value=credential_manager,
        ),
        patch("app.services.model_catalog_service.refresh_runtime_model_catalog", refresh),
    ):
        if catalog_unavailable:
            # A worker must not silently run with incomplete seed-only metadata.
            with pytest.raises(RuntimeError, match="catalog unavailable"):
                await init_worker_credentials()
        else:
            await init_worker_credentials()

    credential_manager.load_with_retry.assert_awaited_once()
    refresh.assert_awaited_once_with(session)
    engine.dispose.assert_awaited_once()
