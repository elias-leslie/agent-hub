"""Tests for scope mapping in memory list/search responses."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.list_operations import list_episodes_paginated
from app.services.memory.memory_models import MemoryScope
from app.services.memory.service_search import text_search


def _mem(
    *,
    mem_id: str,
    group_id: str,
    scope: str = "project",
    scope_id: str | None = "agent-hub",
    name: str | None = "n",
    content: str | None = "c",
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=mem_id,
        group_id=group_id,
        scope=scope,
        scope_id=scope_id,
        tier=3,
        name=name,
        content=content,
        source_description="s",
        created_at=now,
        valid_at=now,
        summary=None,
        loaded_count=0,
        referenced_count=0,
        helpful_count=0,
        harmful_count=0,
        utility_score=0.0,
        pinned=False,
        tags=[],
    )


@pytest.mark.asyncio
async def test_list_episodes_paginated_uses_row_scope_from_group_id() -> None:
    mock_repo = AsyncMock()
    mock_repo.list_paginated = AsyncMock(
        return_value={
            "memories": [_mem(mem_id="123", group_id="project-agent-hub")],
            "has_more": False,
        }
    )

    with patch("app.services.memory.list_operations.get_memory_repository", return_value=mock_repo):
        result = await list_episodes_paginated(
            group_id=None,
            scope=MemoryScope.GLOBAL,
            scope_id=None,
            limit=50,
            cursor=None,
            category=None,
        )

    mock_repo.list_paginated.assert_awaited_once_with(
        group_id=None,
        scope=None,
        scope_id=None,
        category=None,
        limit=50,
        cursor=None,
    )
    assert result.total == 1
    assert result.episodes[0].uuid == "123"
    assert result.episodes[0].scope == MemoryScope.PROJECT
    assert result.episodes[0].scope_id == "agent-hub"


@pytest.mark.asyncio
async def test_text_search_uses_row_scope_from_group_id() -> None:
    mock_repo = AsyncMock()
    mock_repo.text_search = AsyncMock(
        return_value=[_mem(mem_id="456", group_id="project-monkey-fight", scope_id="monkey-fight")]
    )

    with patch("app.services.memory.service_search.get_memory_repository", return_value=mock_repo):
        result = await text_search(
            group_id=None,
            scope=MemoryScope.GLOBAL,
            scope_id=None,
            query="foo",
            limit=10,
            category=None,
        )

    mock_repo.text_search.assert_awaited_once_with(
        "foo",
        group_id=None,
        scope=None,
        category=None,
        limit=10,
    )
    assert len(result) == 1
    assert result[0].uuid == "456"
    assert result[0].scope == MemoryScope.PROJECT
    assert result[0].scope_id == "monkey-fight"


@pytest.mark.asyncio
async def test_list_episodes_paginated_handles_nullable_name_content() -> None:
    mock_repo = AsyncMock()
    mock_repo.list_paginated = AsyncMock(
        return_value={
            "memories": [
                _mem(mem_id="789", group_id="project-agent-hub", name=None, content=None),
            ],
            "has_more": False,
        }
    )

    with patch("app.services.memory.list_operations.get_memory_repository", return_value=mock_repo):
        result = await list_episodes_paginated(
            group_id=None,
            scope=MemoryScope.GLOBAL,
            scope_id=None,
            limit=10,
            cursor=None,
            category=None,
        )

    assert result.total == 1
    assert result.episodes[0].name == ""
    assert result.episodes[0].content == ""
