"""Tests for fresh-database agent bootstrapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent_bootstrap_service import bootstrap_default_agents


class TestBootstrapDefaultAgents:
    @pytest.mark.asyncio
    async def test_runs_seed_agents_and_returns_created_count(self) -> None:
        mock_db = AsyncMock()

        with patch(
            "app.services.agent_bootstrap_service.seed_agents",
            new_callable=AsyncMock,
            return_value=39,
        ) as mock_seed_agents:
            created = await bootstrap_default_agents(mock_db)

        assert created == 39
        mock_seed_agents.assert_awaited_once_with(mock_db)

    @pytest.mark.asyncio
    async def test_returns_zero_when_seed_agents_finds_nothing_to_create(self) -> None:
        mock_db = AsyncMock()

        with patch(
            "app.services.agent_bootstrap_service.seed_agents",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_seed_agents:
            created = await bootstrap_default_agents(mock_db)

        assert created == 0
        mock_seed_agents.assert_awaited_once_with(mock_db)
