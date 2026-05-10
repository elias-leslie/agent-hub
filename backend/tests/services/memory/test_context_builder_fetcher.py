"""Tests for fetch_all_episodes pinned-memory behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.context_builder_fetcher import fetch_all_episodes
from app.services.memory.context_injector_blocks_helpers import mandate_episode_to_result
from app.services.memory.service import MemoryScope, MemorySearchResult, MemorySource


def _result(uuid: str, content: str, *, pinned: bool = False) -> MemorySearchResult:
    return MemorySearchResult(
        uuid=uuid,
        content=content,
        source=MemorySource.SYSTEM,
        relevance_score=1.0,
        created_at=datetime(2026, 3, 14, 13, 0, tzinfo=UTC),
        facts=[content],
        pinned=pinned,
    )


class TestContextBuilderFetcher:
    @pytest.mark.asyncio
    async def test_fetch_all_episodes_includes_pinned_references(self) -> None:
        pinned_reference = _result(
            "pinned-ref",
            "Pinned reference should always be shown while references are enabled.",
            pinned=True,
        )

        with (
            patch(
                "app.services.memory.context_builder_fetcher.get_mandates",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.memory.context_builder_fetcher.get_guardrails",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.memory.context_builder_fetcher.get_auto_inject_references_as_search_results",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.memory.context_builder_fetcher.get_pinned_episodes_as_search_results",
                new=AsyncMock(
                    side_effect=lambda tier, scope, scope_id: [pinned_reference]
                    if tier == "reference"
                    else []
                ),
            ),
        ):
            mandates, guardrails, references = await fetch_all_episodes(
                [(MemoryScope.PROJECT, "agent-hub")],
                include_mandates=True,
                include_guardrails=True,
                include_references=True,
                task_type=None,
                phase=None,
            )

        assert mandates == []
        assert guardrails == []
        assert [item.uuid for item in references] == ["pinned-ref"]

    @pytest.mark.asyncio
    async def test_fetch_all_episodes_dedupes_pinned_items_against_regular_results(self) -> None:
        duplicate_reference = _result(
            "duplicate-ref",
            "Pinned reference is also auto-inject.",
            pinned=True,
        )

        with (
            patch(
                "app.services.memory.context_builder_fetcher.get_mandates",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.memory.context_builder_fetcher.get_guardrails",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.memory.context_builder_fetcher.get_auto_inject_references_as_search_results",
                new=AsyncMock(return_value=[duplicate_reference]),
            ),
            patch(
                "app.services.memory.context_builder_fetcher.get_pinned_episodes_as_search_results",
                new=AsyncMock(
                    side_effect=lambda tier, scope, scope_id: [duplicate_reference]
                    if tier == "reference"
                    else []
                ),
            ),
        ):
            _, _, references = await fetch_all_episodes(
                [(MemoryScope.GLOBAL, None)],
                include_mandates=False,
                include_guardrails=False,
                include_references=True,
                task_type=None,
                phase=None,
            )

        assert [item.uuid for item in references] == ["duplicate-ref"]

    def test_mandate_episode_to_result_keeps_pinned_items_even_if_demoted(self) -> None:
        result = mandate_episode_to_result(
            {
                "uuid": "pinned-demoted",
                "content": "Pinned mandates should still load even if legacy demotion state exists.",
                "pinned": True,
            },
            {"pinned-demoted"},
        )

        assert result is not None
        assert result.uuid == "pinned-demoted"
        assert result.pinned is True

    def test_mandate_episode_to_result_propagates_render_mode(self) -> None:
        result = mandate_episode_to_result(
            {
                "uuid": "with-render-mode",
                "content": "A mandate whose author chose summary rendering.",
                "summary": "be terse",
                "render_mode": "summary",
            },
            set(),
        )

        assert result is not None
        assert result.render_mode == "summary"
