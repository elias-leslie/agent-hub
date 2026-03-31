"""Tests for prefetched heartbeat recall sections."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.workflows._heartbeat_recall import (
    build_heartbeat_recall_sections,
    warm_heartbeat_recall_sections,
)


@pytest.mark.asyncio
async def test_build_heartbeat_recall_sections_prefers_cache() -> None:
    with (
        patch(
            "app.workflows._heartbeat_recall.get_heartbeat_recall_cache",
            new_callable=AsyncMock,
            return_value={
                "recent_heartbeat_digest": "<recent_heartbeat_digest>cached</recent_heartbeat_digest>",
                "recent_idle_history": "<recent_idle_improvement_history>cached</recent_idle_improvement_history>",
                "improvement_signal_digest": "<improvement_signal_digest>cached</improvement_signal_digest>",
            },
        ),
        patch(
            "app.workflows._heartbeat_recall._get_recent_heartbeat_digest",
            new_callable=AsyncMock,
        ) as mock_recent,
    ):
        sections = await build_heartbeat_recall_sections("agent-hub")

    assert sections.recent_heartbeat_digest == "<recent_heartbeat_digest>cached</recent_heartbeat_digest>"
    assert sections.recent_idle_history == "<recent_idle_improvement_history>cached</recent_idle_improvement_history>"
    assert sections.improvement_signal_digest == "<improvement_signal_digest>cached</improvement_signal_digest>"
    mock_recent.assert_not_awaited()


@pytest.mark.asyncio
async def test_warm_heartbeat_recall_sections_persists_cache() -> None:
    with (
        patch(
            "app.workflows._heartbeat_recall.build_heartbeat_recall_sections",
            new_callable=AsyncMock,
            return_value=type(
                "RecallSections",
                (),
                {
                    "recent_heartbeat_digest": "heartbeat",
                    "recent_idle_history": "idle",
                    "improvement_signal_digest": "signals",
                },
            )(),
        ),
        patch(
            "app.workflows._heartbeat_recall.set_heartbeat_recall_cache",
            new_callable=AsyncMock,
        ) as mock_set,
    ):
        sections = await warm_heartbeat_recall_sections("agent-hub")

    assert sections.recent_heartbeat_digest == "heartbeat"
    mock_set.assert_awaited_once_with(
        project_id="agent-hub",
        recent_heartbeat_digest="heartbeat",
        recent_idle_history="idle",
        improvement_signal_digest="signals",
    )
