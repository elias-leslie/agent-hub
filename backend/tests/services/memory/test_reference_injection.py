"""Focused tests for query-relevant reference injection."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.context_builder import build_progressive_context
from app.services.memory.context_injector import format_context_with_reference_index
from app.services.memory.service import MemoryScope, MemorySearchResult, MemorySource
from app.services.memory.settings import MemorySettingsDTO


def _reference_result(uuid: str, content: str, score: float = 0.72) -> MemorySearchResult:
    return MemorySearchResult(
        uuid=uuid,
        content=content,
        source=MemorySource.SYSTEM,
        relevance_score=score,
        created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
        facts=[content],
        scope=MemoryScope.PROJECT,
    )


class TestReferenceInjection:
    @pytest.mark.asyncio
    async def test_build_progressive_context_injects_query_relevant_references(self) -> None:
        settings = MemorySettingsDTO(
            enabled=True,
            budget_enabled=True,
            total_budget=3500,
            max_mandates=0,
            max_guardrails=0,
            reference_index_enabled=True,
            continuity_enabled=True,
            continuity_max_sessions=5,
        )

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=([], [], [])),
            ),
            patch(
                "app.services.memory.context_builder.get_query_relevant_references_as_search_results",
                new=AsyncMock(
                    return_value=[
                        _reference_result(
                            "f2ae2668-da26-46e1-b499-ffac6141e377",
                            "**Session Surfaces**: Use st sessions ownership for normalized lane truth.",
                        ).model_dump()
                    ]
                ),
            ),
            patch(
                "app.services.memory.context_builder.get_memory_settings",
                new=AsyncMock(return_value=settings),
            ),
        ):
            context = await build_progressive_context(
                query="Why does st sessions ownership differ from st sessions list -s active?",
                scope=MemoryScope.PROJECT,
                scope_id="summitflow",
            )

        assert len(context.reference) == 1
        assert context.reference[0].uuid.startswith("f2ae2668")
        assert context.debug_info["reference_count"] == 1
        assert context.budget_usage is not None
        assert context.budget_usage.reference_tokens > 0

    @pytest.mark.asyncio
    async def test_build_progressive_context_dedupes_selected_references(self) -> None:
        existing = _reference_result(
            "f2ae2668-da26-46e1-b499-ffac6141e377",
            "**Session Surfaces**: Existing ref.",
        )
        new = _reference_result(
            "015a8754-95f0-4370-8a8c-077ace49ca90",
            "**Operator Context**: Expect st context to show SPECIALISTS lines.",
        )
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=([], [], [existing])),
            ),
            patch(
                "app.services.memory.context_builder.get_query_relevant_references_as_search_results",
                new=AsyncMock(return_value=[existing.model_dump(), new.model_dump()]),
            ),
            patch(
                "app.services.memory.context_builder.get_memory_settings",
                new=AsyncMock(return_value=settings),
            ),
        ):
            context = await build_progressive_context(
                query="Show specialist overlap in st context",
                scope=MemoryScope.PROJECT,
                scope_id="summitflow",
            )

        assert [item.uuid for item in context.reference] == [
            "f2ae2668-da26-46e1-b499-ffac6141e377",
            "015a8754-95f0-4370-8a8c-077ace49ca90",
        ]

    def test_format_context_with_reference_index_renders_selected_references_and_excludes_them_from_index(
        self,
    ) -> None:
        context = type("Ctx", (), {})()
        context.mandates = []
        context.guardrails = []
        context.reference = [
            _reference_result(
                "f2ae2668-da26-46e1-b499-ffac6141e377",
                "**Session Surfaces**: Use st sessions ownership for normalized lane truth.",
            )
        ]

        result = format_context_with_reference_index(
            context,
            reference_episodes=[
                (
                    "015a8754-95f0-4370-8a8c-077ace49ca90",
                    "Done path + specialists",
                    "**Operator Context**: Expect st context to show SPECIALISTS lines.",
                    False,
                )
            ],
            include_citations=True,
        )

        assert "## References" in result
        assert "[R:f2ae2668]" in result
        assert "## Reference Index" in result
        assert "015a8754" in result
