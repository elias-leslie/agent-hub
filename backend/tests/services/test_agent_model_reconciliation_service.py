"""Tests for startup agent model assignment reconciliation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.agent_model_reconciliation_service import (
    reconcile_agent_models_to_available_providers,
)


@pytest.mark.asyncio
async def test_reconciliation_noops_after_adaptive_router_removal() -> None:
    mock_db = AsyncMock()

    changed = await reconcile_agent_models_to_available_providers(mock_db)

    assert changed == []
