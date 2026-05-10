"""Tests for copy_episode_stats preserving list-order and feedback data."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.episode_properties import copy_episode_stats


@pytest.mark.asyncio
async def test_copy_episode_stats_forwards_created_at() -> None:
    """Edit-creates-new flow must preserve created_at so the memory list
    (sorted by display_order, created_at desc) doesn't reshuffle the
    edited memory within its bucket."""
    original_created_at = datetime(2026, 1, 15, 12, 30, tzinfo=UTC)
    source = {
        "uuid": "source-uuid",
        "loaded_count": 7,
        "referenced_count": 3,
        "helpful_count": 2,
        "harmful_count": 0,
        "pinned": True,
        "auto_inject": False,
        "display_order": 50,
        "summary": "use st check",
        "trigger_task_types": [],
        "trigger_phases": [],
        "tags": [],
        "context_kind": "policy",
        "applicability": {},
        "created_at": original_created_at,
    }

    repo = AsyncMock()
    repo.get_as_dict.return_value = source
    repo.update.return_value = True

    with patch(
        "app.services.memory.episode_properties.get_memory_repository",
        return_value=repo,
    ):
        ok = await copy_episode_stats("source-uuid", "target-uuid")

    assert ok is True
    repo.update.assert_awaited_once()
    kwargs = repo.update.await_args.kwargs
    assert kwargs["created_at"] == original_created_at


@pytest.mark.asyncio
async def test_copy_episode_stats_skips_created_at_when_missing() -> None:
    """Defensive: if the source row somehow lacks created_at, don't pass None."""
    source = {
        "uuid": "source-uuid",
        "loaded_count": 0,
        "display_order": 50,
        "context_kind": "reference",
    }

    repo = AsyncMock()
    repo.get_as_dict.return_value = source
    repo.update.return_value = True

    with patch(
        "app.services.memory.episode_properties.get_memory_repository",
        return_value=repo,
    ):
        ok = await copy_episode_stats("source-uuid", "target-uuid")

    assert ok is True
    kwargs = repo.update.await_args.kwargs
    assert "created_at" not in kwargs
