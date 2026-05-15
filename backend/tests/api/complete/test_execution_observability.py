from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.execution_observability import (
    build_execution_observability,
    persist_execution_observability,
)


def test_build_execution_observability_uses_tool_budget_and_max_turn_stop_reason() -> None:
    session = SimpleNamespace(agent_slug="refactor", client_id="client-1", request_source="cli")

    execution = build_execution_observability(
        session=session,
        provider="codex",
        requested_max_turns=1,
        orchestration_path="tool_loop",
        final_finish_reason="max_turns",
        execution_status="success",
        execution_error=None,
        turns_completed=20,
        tool_calls_count=4,
    )

    assert execution["orchestration_path"] == "tool_loop"
    assert execution["requested_max_turns"] == 1
    assert execution["effective_turn_budget"] == 3
    assert execution["terminal_stop_reason"] == "max_turns"
    assert execution["agent_slug"] == "refactor"
    assert execution["client_id"] == "client-1"
    assert execution["request_source"] == "cli"


def test_build_execution_observability_preserves_uncapped_tool_loop() -> None:
    session = SimpleNamespace(agent_slug="coder", client_id=None, request_source="summitflow")

    execution = build_execution_observability(
        session=session,
        provider="codex",
        requested_max_turns=None,
        orchestration_path="tool_loop",
        final_finish_reason="stop",
        execution_status="success",
        execution_error=None,
        turns_completed=200,
        tool_calls_count=40,
    )

    assert execution["requested_max_turns"] is None
    assert execution["effective_turn_budget"] is None
    assert execution["terminal_stop_reason"] == "stop"


@pytest.mark.asyncio
async def test_persist_execution_observability_updates_session_metadata_and_stores_tool_audit() -> None:
    db = AsyncMock()
    session = SimpleNamespace(
        provider_metadata={},
        agent_slug="debugger",
        client_id="client-2",
        request_source="summitflow/task",
    )

    with patch(
        "app.api.complete.execution_observability.store_event",
        new_callable=AsyncMock,
    ) as mock_store:
        execution = await persist_execution_observability(
            db,
            session,
            "sess-2",
            provider="claude",
            model_used="claude-sonnet-4-6",
            requested_max_turns=4,
            orchestration_path="multi_turn",
            final_finish_reason="end_turn",
            execution_status="success",
            execution_error=None,
            turns_completed=3,
            tool_calls_count=0,
        )

    assert session.provider_metadata["execution"] == execution
    assert execution["effective_turn_budget"] == 4
    assert execution["terminal_stop_reason"] == "end_turn"
    await_args = mock_store.await_args
    assert await_args is not None
    assert await_args.kwargs["event_type"] == "tool_audit"
    assert await_args.kwargs["tool_name"] == "execution_observability"
    assert await_args.kwargs["tool_output"] == execution
