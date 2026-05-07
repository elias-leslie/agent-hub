"""Tests for startup adaptive routing reconciliation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models import Agent
from app.services.agent_model_reconciliation_service import (
    reconcile_agent_models_to_available_providers,
)


def _agent() -> Agent:
    return Agent(
        slug="persona",
        name="Jenny",
        description=None,
        system_prompt="test",
        primary_model_id="codex/gpt-5.5",
        fallback_models=["claude-sonnet-4-6"],
        escalation_model_id=None,
        strategies={},
        temperature=0.1,
        thinking_level="medium",
        verbosity_level=None,
        is_active=True,
        is_coding_agent=False,
        memory_config=None,
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
    )


@pytest.mark.asyncio
async def test_reconciliation_seeds_routing_metadata_without_rewriting_agent_models() -> None:
    agent = _agent()
    mock_db = AsyncMock()

    with patch(
        "app.services.agent_model_reconciliation_service.ensure_adaptive_routing_seed_data",
        new=AsyncMock(return_value=4),
    ) as seed:
        changed = await reconcile_agent_models_to_available_providers(mock_db)

    assert changed == ["adaptive-routing:4"]
    assert agent.primary_model_id == "codex/gpt-5.5"
    assert agent.fallback_models == ["claude-sonnet-4-6"]
    seed.assert_awaited_once_with(mock_db)


@pytest.mark.asyncio
async def test_reconciliation_noops_when_seed_data_already_exists() -> None:
    mock_db = AsyncMock()

    with patch(
        "app.services.agent_model_reconciliation_service.ensure_adaptive_routing_seed_data",
        new=AsyncMock(return_value=0),
    ):
        changed = await reconcile_agent_models_to_available_providers(mock_db)

    assert changed == []
