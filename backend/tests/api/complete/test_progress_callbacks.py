"""Tests for progress callback failure handling."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.api.complete.tool_models import AgentProgress
from app.api.complete.tool_progress import ProgressTracker
from app.api.complete.turn_processor import report_progress


@pytest.mark.asyncio
async def test_progress_tracker_swallows_callback_errors() -> None:
    callback = AsyncMock(side_effect=RuntimeError("stream unavailable"))
    tracker = ProgressTracker(callback=callback)

    await tracker.report_complete(turn=2, tool_calls_count=4)

    assert len(tracker.log) == 1
    assert tracker.log[0].status == "complete"
    callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_report_progress_swallows_callback_errors() -> None:
    callback = AsyncMock(side_effect=RuntimeError("stream unavailable"))
    progress = AgentProgress(turn=3, status="complete", message="done")

    await report_progress(progress, callback)

    callback.assert_awaited_once_with(progress)
