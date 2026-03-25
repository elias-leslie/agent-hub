"""Regression tests for read-side memory fallback behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.context_injector_queries import get_query_relevant_references
from app.services.memory.memory_models import MemoryCategory, MemoryScope
from app.services.memory.search_context import get_context_for_query
from app.services.memory.search_patterns import get_patterns_and_gotchas
from app.services.memory.search_semantic import search_memory


def _mem(
    *,
    mem_id: str,
    content: str,
    tier: int = 3,
    name: str | None = None,
    summary: str | None = None,
    pinned: bool = False,
    tags: list[str] | None = None,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=mem_id,
        version=1,
        content=content,
        name=name or content[:20],
        summary=summary,
        memory_type="memory",
        context_kind="reference" if tier == 3 else "policy",
        applicability={},
        scope="global",
        scope_id=None,
        group_id="global",
        source="chat",
        source_description="reference",
        tags=tags or [],
        injection_tier="reference",
        tier=tier,
        pinned=pinned,
        auto_inject=False,
        display_order=0,
        trigger_task_types=[],
        trigger_phases=[],
        loaded_count=0,
        referenced_count=0,
        helpful_count=0,
        harmful_count=0,
        utility_score=0.0,
        status="active",
        token_count=10,
        lifecycle_score=None,
        lifecycle_score_updated_at=None,
        retired_at=None,
        superseded_by=None,
        metadata_={},
        valid_at=now,
        created_at=now,
        updated_at=now,
        last_accessed_at=None,
    )


@pytest.mark.asyncio
async def test_search_memory_falls_back_to_text_when_embedder_unavailable() -> None:
    repo = AsyncMock()
    repo.text_search = AsyncMock(return_value=[_mem(mem_id="text-hit", content="branch cleanup rule")])
    repo.increment_loaded = AsyncMock()

    with (
        patch("app.services.memory.search_semantic.get_memory_repository", return_value=repo),
        patch("app.services.memory.search_semantic.get_embedder_or_none", return_value=None),
    ):
        results = await search_memory(
            group_id=None,
            scope=MemoryScope.GLOBAL,
            query="branch cleanup",
            limit=5,
            min_score=0.0,
        )

    assert [result.uuid for result in results] == ["text-hit"]
    assert results[0].content == "branch cleanup rule"
    repo.increment_loaded.assert_awaited_once_with(["text-hit"])


@pytest.mark.asyncio
async def test_query_relevant_references_falls_back_to_text_when_embedder_unavailable() -> None:
    repo = AsyncMock()
    repo.text_search = AsyncMock(
        return_value=[
            _mem(
                mem_id="ref-hit",
                content="Use st agents preview before guessing runtime prompt state.",
                summary="Preview runtime prompt state.",
                tier=3,
            )
        ]
    )

    with (
        patch("app.services.memory.context_injector_queries.get_memory_repository", return_value=repo),
        patch("app.services.memory.embedder.get_embedder_or_none", return_value=None),
        patch(
            "app.services.memory.context_injector_queries.MemoryRepository._to_dict",
            side_effect=lambda mem: {
                "uuid": str(mem.id),
                "id": str(mem.id),
                "content": mem.content,
                "name": mem.name,
                "summary": mem.summary,
                "scope": mem.scope,
                "source_description": mem.source_description,
                "metadata": mem.metadata_,
                "tier": mem.tier,
                "pinned": mem.pinned,
                "tags": mem.tags,
            },
        ),
    ):
        results = await get_query_relevant_references(
            "preview runtime prompt state",
            [(MemoryScope.PROJECT, "agent-hub")],
            limit=3,
        )

    assert [result["uuid"] for result in results] == ["ref-hit"]
    assert results[0]["content"].startswith("Use st agents preview")
    repo.semantic_search.assert_not_called()


@pytest.mark.asyncio
async def test_get_context_for_query_falls_back_to_text_when_embedder_unavailable() -> None:
    repo = AsyncMock()
    repo.text_search = AsyncMock(
        return_value=[
            _mem(mem_id="ctx-hit", content="Run dt -q -d before commit.", tier=1, name="Quality Tool Usage")
        ]
    )
    repo.increment_loaded = AsyncMock()

    with (
        patch("app.services.memory.search_context.get_memory_repository", return_value=repo),
        patch("app.services.memory.search_context.get_embedder_or_none", return_value=None),
    ):
        context = await get_context_for_query(
            group_id=None,
            scope=MemoryScope.GLOBAL,
            query="quality checks before commit",
            max_facts=5,
            max_entities=5,
        )

    assert context.relevant_facts == ["Run dt -q -d before commit."]
    assert context.episodes[0].uuid == "ctx-hit"
    repo.increment_loaded.assert_awaited_once_with(["ctx-hit"])


@pytest.mark.asyncio
async def test_get_patterns_and_gotchas_falls_back_to_text_when_embedder_unavailable() -> None:
    repo = AsyncMock()
    repo.text_search = AsyncMock(
        return_value=[
            _mem(mem_id="pattern-hit", content="Use named exports only.", tier=3),
            _mem(mem_id="gotcha-hit", content="Never bypass access control checks.", tier=2),
        ]
    )
    repo.increment_loaded = AsyncMock()

    with (
        patch("app.services.memory.search_patterns.get_memory_repository", return_value=repo),
        patch("app.services.memory.search_patterns.get_embedder_or_none", return_value=None),
    ):
        patterns, gotchas = await get_patterns_and_gotchas(
            group_id=None,
            scope=MemoryScope.GLOBAL,
            query="exports access control",
            num_results=5,
            min_score=0.5,
        )

    assert [item.category for item in patterns] == [MemoryCategory.REFERENCE]
    assert [item.category for item in gotchas] == [MemoryCategory.GUARDRAIL]
    assert patterns[0].uuid == "pattern-hit"
    assert gotchas[0].uuid == "gotcha-hit"
    repo.increment_loaded.assert_awaited_once_with(["pattern-hit", "gotcha-hit"])
