"""Search results carry a memory's own scope, scope_id and render_mode, as /list does."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory._repo_search import SearchRepository
from app.services.memory.memory_models import MemoryScope
from app.services.memory.search_helpers import build_search_result_from_dict
from app.services.memory.search_semantic import search_memory


def _project_row() -> dict:
    return {
        "id": "mem-1",
        "content": "Run st check before committing.",
        "summary": "st check first",
        "scope": "project",
        "scope_id": "agent-hub",
        "group_id": "project:agent-hub",
        "tier": 3,
        "render_mode": "summary",
        "relevance_score": 0.9,
        "created_at": datetime(2026, 10, 1, tzinfo=UTC),
    }


@pytest.mark.asyncio
async def test_hybrid_search_keeps_scope_scope_id_and_render_mode() -> None:
    repo = AsyncMock()
    repo.text_search = AsyncMock(return_value=[])
    repo.semantic_search = AsyncMock(return_value=[_project_row()])
    repo.increment_loaded = AsyncMock()
    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[0.1, 0.2])

    with (
        patch("app.services.memory.search_semantic.get_memory_repository", return_value=repo),
        patch("app.services.memory.search_semantic.get_embedder_or_none", return_value=embedder),
    ):
        [result] = await search_memory(
            group_id=None, scope=MemoryScope.GLOBAL, query="st check", limit=5,
        )

    assert result.scope == MemoryScope.PROJECT
    assert result.scope_id == "agent-hub"
    assert result.render_mode == "summary"


def test_dict_search_result_keeps_scope_scope_id_and_render_mode() -> None:
    result = build_search_result_from_dict(_project_row(), MemoryScope.GLOBAL)

    assert result.scope == MemoryScope.PROJECT
    assert result.scope_id == "agent-hub"
    assert result.render_mode == "summary"


def test_dict_search_result_falls_back_to_caller_scope_without_row_scope() -> None:
    row = _project_row()
    row.pop("scope")
    row.pop("scope_id")

    result = build_search_result_from_dict(row, MemoryScope.GLOBAL)

    assert result.scope == MemoryScope.GLOBAL
    assert result.scope_id is None


@pytest.mark.asyncio
async def test_semantic_search_selects_render_mode() -> None:
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(mappings=MagicMock(return_value=MagicMock(
        all=MagicMock(return_value=[])
    ))))

    await SearchRepository().semantic_search([0.1], db=db)

    call = db.execute.await_args
    assert call is not None
    sql = str(call.args[0])
    assert "render_mode" in sql
