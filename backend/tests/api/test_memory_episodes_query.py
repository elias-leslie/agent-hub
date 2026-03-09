"""Tests for memory episodes query handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.api.memory_episodes_query import handle_get_memory_stats, handle_list_episodes
from app.api.memory_episodes_search import handle_search_memory, handle_text_search_memory


@pytest.mark.asyncio
async def test_handle_list_episodes_defaults_all_groups_false() -> None:
    memory = AsyncMock()
    memory.list_episodes = AsyncMock(return_value={"memories": [], "total": 0})

    await handle_list_episodes(
        memory=memory,
        limit=25,
        cursor=None,
        category=None,
    )

    memory.list_episodes.assert_awaited_once_with(
        limit=25,
        cursor=None,
        category=None,
        all_groups=False,
    )


@pytest.mark.asyncio
async def test_handle_get_memory_stats_defaults_all_groups_false() -> None:
    memory = AsyncMock()
    memory.get_stats = AsyncMock(return_value={"total": 0})

    await handle_get_memory_stats(memory=memory)

    memory.get_stats.assert_awaited_once_with(all_groups=False)


@pytest.mark.asyncio
async def test_handle_get_memory_stats_passes_all_groups_true() -> None:
    memory = AsyncMock()
    memory.get_stats = AsyncMock(return_value={"total": 0})

    await handle_get_memory_stats(memory=memory, all_groups=True)

    memory.get_stats.assert_awaited_once_with(all_groups=True)


@pytest.mark.asyncio
async def test_handle_search_memory_respects_scope_filters() -> None:
    memory = AsyncMock()
    memory.search = AsyncMock(return_value=[])

    await handle_search_memory(
        query="coderabbit",
        memory=memory,
        limit=10,
        min_score=0.0,
    )

    memory.search.assert_awaited_once_with(
        query="coderabbit",
        limit=10,
        min_score=0.0,
        all_groups=False,
    )


@pytest.mark.asyncio
async def test_handle_text_search_memory_respects_scope_filters() -> None:
    memory = AsyncMock()
    memory.text_search = AsyncMock(return_value=[])

    await handle_text_search_memory(
        query="coderabbit",
        memory=memory,
        limit=10,
        category=None,
    )

    memory.text_search.assert_awaited_once_with(
        query="coderabbit",
        limit=10,
        category=None,
        all_groups=False,
    )
