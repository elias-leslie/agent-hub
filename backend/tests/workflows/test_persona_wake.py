"""Tests for agent wake prompt shaping and summary post-processing."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.workflows.persona_wake import WakeInput, _build_wake_prompt, agent_wake_task


def _mock_async_session(mock_db):
    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session


def test_build_wake_prompt_includes_current_st_guidance():
    prompt = _build_wake_prompt("Investigate the current task branch.")

    assert "st ready-all" in prompt
    assert "st ready --limit N" in prompt
    assert "st sessions list --status <status> --limit N" in prompt
    assert "st session-events <session_id>" in prompt
    assert "st session-events -T task-123 --page-size 100" in prompt
    assert "Do not add stale flags like `-P`, `--project`, `--human`, or `--compact`" in prompt
    assert "Do not use `--session` with `st session-events`" in prompt
    assert "Do not treat `st sessions list` output `session_id` values like Agent Hub session ids" in prompt
    assert "Avoid exploratory `--help` calls unless a known-good command above still fails." in prompt
    assert "Task:\nInvestigate the current task branch." in prompt


@pytest.mark.asyncio
async def test_agent_wake_stores_summary_for_completed_session():
    mock_db = AsyncMock()
    complete_result = SimpleNamespace(
        status="success",
        turns=4,
        tool_calls_count=3,
        error=None,
        session_id="sess-wake-1",
        content="Investigated worktree and found valid in-progress work.",
    )
    mock_perm = SimpleNamespace(permission_tier="yolo")
    mock_persona = SimpleNamespace(limits=None)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.project_permission_service.get_project_permission",
            new_callable=AsyncMock,
            return_value=mock_perm,
        ),
        patch(
            "app.services.persona_service.get_persona",
            new_callable=AsyncMock,
            return_value=mock_persona,
        ),
        patch(
            "app.services._persona_crud.get_persona_limit",
            return_value=200,
        ),
        patch(
            "app.api.complete.core.complete_internal",
            new_callable=AsyncMock,
            return_value=complete_result,
        ) as mock_complete,
        patch(
            "app.workflows.persona_wake.ensure_session_summary",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_summary,
    ):
        result = await agent_wake_task.aio_mock_run(
            WakeInput(
                agent_slug="debugger",
                model="codex/gpt-5.4",
                provider="codex",
                prompt="Inspect the dirty worktree and decide if it is valid progress.",
                project_id="terminal",
                event_type="dispatch",
                thinking_level="medium",
                max_turns=25,
            )
        )

    assert result["summary_stored"] is True
    mock_summary.assert_awaited_once_with(
        "sess-wake-1",
        "Investigated worktree and found valid in-progress work.",
        agent_id="debugger",
    )
    messages = mock_complete.await_args.kwargs["messages"]
    assert len(messages) == 1
    assert "st ready-all" in messages[0]["content"]
    assert "Task:\nInspect the dirty worktree" in messages[0]["content"]
