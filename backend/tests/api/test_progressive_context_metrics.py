"""Compatibility and resilience tests for the canonical progressive surface."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api.memory_agent_handlers import build_progressive_context_response
from app.api.memory_agent_schemas import ProgressiveContextBlock, ProgressiveContextResponse
from app.services.memory.service import MemoryScope

_HANDLER = "app.api.memory_agent_handlers"


@pytest.mark.asyncio
async def test_progressive_context_retries_transient_canonical_failure() -> None:
    ok_response = ProgressiveContextResponse(
        mandates=ProgressiveContextBlock(items=[], count=0),
        guardrails=ProgressiveContextBlock(items=[], count=0),
        reference=ProgressiveContextBlock(items=[], count=0),
        total_tokens=0,
        formatted="canonical formatted",
        variant="BASELINE",
        canonical_context={"payload_hash": "hash", "block_ids": []},
    )

    with (
        patch(
            f"{_HANDLER}._build_progressive_context_response_once",
            new=AsyncMock(side_effect=[RuntimeError("temporary"), ok_response]),
        ) as mock_once,
        patch("app.services.memory.context_resilience.asyncio.sleep", new=AsyncMock()),
    ):
        response = await build_progressive_context_response(
            query="test",
            scope=MemoryScope.GLOBAL,
            scope_id=None,
            debug=False,
            include_global=True,
            task_type=None,
        )

    assert response.status == "ok"
    assert response.formatted == "canonical formatted"
    assert response.canonical_context == {"payload_hash": "hash", "block_ids": []}
    assert response.attempts == 2
    assert mock_once.await_count == 2


@pytest.mark.asyncio
async def test_progressive_context_fails_closed_after_canonical_retries() -> None:
    with (
        patch(
            f"{_HANDLER}._build_progressive_context_response_once",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ) as mock_once,
        patch("app.services.memory.context_resilience.asyncio.sleep", new=AsyncMock()),
    ):
        response = await build_progressive_context_response(
            query="test",
            scope=MemoryScope.PROJECT,
            scope_id="agent-hub",
            debug=False,
            include_global=True,
            task_type=None,
            project_id="agent-hub",
            consumer_profile="agent_startup",
        )

    assert response.status == "failed"
    assert response.failure is not None
    assert response.failure.attempts == 3
    assert "Stop substantive work immediately" in response.formatted
    assert mock_once.await_count == 3
