"""Tests for agent assignment model routing."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.constants.models import GEMINI_FLASH, KIMI_CODE_FOR_CODING
from app.services.agent_dto import AgentDTO
from app.services.agent_model_router import (
    RoutingContext,
    RoutingSelectionError,
    resolve_model_route,
)


def _agent(**overrides: object) -> AgentDTO:
    now = datetime.now(UTC)
    values = {
        "id": 1,
        "slug": "portfolio-mgr-v1",
        "name": "Portfolio Manager",
        "description": None,
        "system_prompt": "test",
        "primary_model_id": KIMI_CODE_FOR_CODING,
        "fallback_models": [GEMINI_FLASH],
        "escalation_model_id": None,
        "strategies": {},
        "temperature": 0.1,
        "thinking_level": "medium",
        "verbosity_level": None,
        "is_active": True,
        "is_coding_agent": False,
        "memory_config": None,
        "max_concurrency": None,
        "max_subagent_concurrency": None,
        "daily_token_budget": None,
        "hourly_request_limit": None,
        "timeout_seconds": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return AgentDTO(**values)


@pytest.mark.asyncio
async def test_resolve_model_route_uses_agent_assignment_chain() -> None:
    agent, route = await resolve_model_route(
        AsyncMock(),
        _agent(),
        RoutingContext(),
    )

    assert agent.primary_model_id == KIMI_CODE_FOR_CODING
    assert agent.fallback_models == [GEMINI_FLASH]
    assert route.primary_model_id == KIMI_CODE_FOR_CODING
    assert route.fallback_models == [GEMINI_FLASH]
    assert route.mode == "agent_assignment"
    assert route.provider == "kimi-code"
    assert route.score_breakdown == {"agent_assignment_chain": True}


@pytest.mark.asyncio
async def test_resolve_model_route_requires_agent_primary_assignment() -> None:
    with pytest.raises(RoutingSelectionError, match="no primary_model_id"):
        await resolve_model_route(AsyncMock(), _agent(primary_model_id=""))
