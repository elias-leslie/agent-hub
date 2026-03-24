"""Dispatch tests for CodeRabbit review follow-up."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.workflows.coderabbit_review import ReviewResult, _wake_persona_with_findings


@pytest.mark.asyncio
async def test_wake_persona_with_findings_dispatches_async_wake() -> None:
    @asynccontextmanager
    async def fake_session():
        yield object()

    fake_agent = SimpleNamespace(
        primary_model_id="codex/gpt-5.4",
        temperature=0.2,
        thinking_level="medium",
    )
    fake_agent_service = SimpleNamespace(get_by_slug=AsyncMock(return_value=fake_agent))
    result = ReviewResult(
        status="success",
        projects_reviewed=1,
        total_findings=2,
        project_summaries={"agent-hub": "Type: bug\nSummary: example finding"},
    )

    with (
        patch("app.db.async_session", fake_session),
        patch("app.services.agent_service.get_agent_service", return_value=fake_agent_service),
        patch("app.services.agent_routing.get_provider_for_model", return_value="codex"),
        patch("app.workflows.persona_wake.agent_wake_task") as mock_task,
    ):
        mock_task.aio_run_no_wait = AsyncMock()
        await _wake_persona_with_findings(result)

    fake_agent_service.get_by_slug.assert_awaited_once()
    mock_task.aio_run_no_wait.assert_awaited_once()
    wake_input = mock_task.aio_run_no_wait.call_args.kwargs["input"]
    assert wake_input.agent_slug == "persona"
    assert wake_input.project_id == "summitflow"
    assert wake_input.event_type == "coderabbit_review"


@pytest.mark.asyncio
async def test_wake_persona_with_findings_skips_when_no_actionable_findings() -> None:
    result = ReviewResult(
        status="success",
        projects_reviewed=1,
        total_findings=0,
        project_summaries={"agent-hub": "Clean — no findings"},
    )

    with patch("app.workflows.persona_wake.agent_wake_task") as mock_task:
        mock_task.aio_run_no_wait = AsyncMock()
        await _wake_persona_with_findings(result)

    mock_task.aio_run_no_wait.assert_not_awaited()
