"""Tests for session summary workflow integration with session analysis."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.memory_dashboard_helpers import run_sync_summarize


@pytest.mark.asyncio
async def test_run_sync_summarize_passes_transcript_path_to_background_analysis() -> None:
    """Sync summary path must schedule transcript-aware session analysis."""
    background_tasks: set[asyncio.Task[object]] = set()
    summary_result = SimpleNamespace(skipped=False, ratings={})

    with (
        patch(
            "app.services.memory.summary_generator.generate_session_summary",
            new_callable=AsyncMock,
            return_value=summary_result,
        ),
        patch(
            "app.services.memory.session_analysis.analyze_session",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                citations_credited=1,
                feedback_created=1,
                summary_stored=True,
            ),
        ) as mock_analyze,
    ):
        result = await run_sync_summarize(
            background_tasks=background_tasks,
            session_id="session-123",
            project_id="agent-hub",
            branch="main",
            transcript_path="/tmp/codex-session.jsonl",
            git_context="abc1234 feat: test",
        )
        if background_tasks:
            await asyncio.gather(*background_tasks)

    assert result is summary_result
    mock_analyze.assert_awaited_once_with(
        "session-123",
        transcript_path="/tmp/codex-session.jsonl",
    )


@pytest.mark.asyncio
async def test_session_summary_task_runs_transcript_aware_analysis() -> None:
    """Async summary task must persist citations/feedback from transcript-only sessions."""
    from app.workflows.summary import SummaryInput, session_summary_task

    summary_result = SimpleNamespace(
        skipped=False,
        outcome="completed",
        summary="Implemented transcript analysis",
        git_digest="abc1234 feat: wire transcript analysis",
        ratings={},
    )
    analysis_result = SimpleNamespace(
        citations_credited=3,
        feedback_created=2,
        summary_stored=True,
    )

    with (
        patch(
            "app.services.memory.summary_generator.generate_session_summary",
            new_callable=AsyncMock,
            return_value=summary_result,
        ),
        patch(
            "app.services.memory.session_analysis.analyze_session",
            new_callable=AsyncMock,
            return_value=analysis_result,
        ) as mock_analyze,
        patch(
            "app.workflows.summary._apply_memory_ratings",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        result = await session_summary_task.aio_mock_run(
            SummaryInput(
                session_id="session-123",
                branch="main",
                transcript_path="/tmp/codex-session.jsonl",
                git_context="abc1234 feat: wire transcript analysis",
            ),
        )

    mock_analyze.assert_awaited_once_with(
        "session-123",
        transcript_path="/tmp/codex-session.jsonl",
        git_context="abc1234 feat: wire transcript analysis",
        branch="main",
    )
    assert result["citations_credited"] == 3
    assert result["feedback_created"] == 2
    assert result["summary_stored"] is True
