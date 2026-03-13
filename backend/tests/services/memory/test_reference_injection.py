"""Focused tests for query-relevant reference injection."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.context_builder import build_progressive_context
from app.services.memory.context_injector import format_context_with_reference_index
from app.services.memory.context_injector_blocks_helpers import episode_to_result
from app.services.memory.context_injector_queries import build_reference_toon_index
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
    def test_episode_to_result_normalizes_null_tags(self) -> None:
        result = episode_to_result(
            {
                "uuid": "f2ae2668-da26-46e1-b499-ffac6141e377",
                "content": "**Session Surfaces**: Use ownership for normalized lane truth.",
                "tags": None,
            }
        )

        assert result is not None
        assert result.tags == []

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
    async def test_build_progressive_context_assigns_render_tiers_and_saves_chars(self) -> None:
        long_guardrail = (
            "Never bypass authentication middleware. Always debug the root cause, preserve the access check, "
            "and confirm the real credentials or test setup problem before changing code paths. "
            "Do not patch around auth failures, do not disable middleware for tests, and do not replace "
            "authorization logic with temporary bypasses while investigating."
        )
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
                new=AsyncMock(
                    return_value=(
                        [
                            MemorySearchResult(
                                uuid="mandate-uuid",
                                content="Use AsyncAgentHubClient for Agent Hub completions.",
                                summary="Use AsyncAgentHubClient",
                                source=MemorySource.SYSTEM,
                                relevance_score=1.0,
                                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                                facts=[],
                            )
                        ],
                        [
                            MemorySearchResult(
                                uuid="guardrail-uuid",
                                content=long_guardrail,
                                summary="Preserve auth middleware",
                                source=MemorySource.SYSTEM,
                                relevance_score=0.9,
                                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                                facts=[],
                            )
                        ],
                        [],
                    )
                ),
            ),
            patch(
                "app.services.memory.context_builder.get_query_relevant_references_as_search_results",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.memory.context_builder.get_memory_settings",
                new=AsyncMock(return_value=settings),
            ),
        ):
            context = await build_progressive_context(
                query="How should Agent Hub completions call the SDK?",
                scope=MemoryScope.PROJECT,
                scope_id="agent-hub",
            )

        assert context.mandates[0].render_tier == "L2"
        assert context.guardrails[0].render_tier == "L1"
        assert context.guardrails[0].rendered_content is not None
        assert len(context.guardrails[0].rendered_content) < len(long_guardrail)
        assert context.debug_info["tier_counts"] == {"L1": 1, "L2": 1}
        assert context.debug_info["render_chars_saved"] > 0
        assert context.debug_info["memory_plan"][0]["uuid"] == "mandate-uuid"
        assert context.debug_info["memory_plan"][1]["tier"] == "L1"

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

    @pytest.mark.asyncio
    async def test_build_reference_toon_index_skips_operational_noise(self) -> None:
        with patch(
            "app.services.memory.context_injector_queries.get_episodes_by_tier",
            new=AsyncMock(
                return_value=[
                    {
                        "uuid": "good-uuid",
                        "summary": "Service scripts",
                        "content": "**Service Scripts**: Use rebuild.sh for frontend changes.",
                        "pinned": False,
                        "metadata": {},
                        "source_description": "learning",
                    },
                    {
                        "uuid": "summary-uuid",
                        "summary": "Session summary",
                        "content": "[Session Summary: abc]\nSomething happened.",
                        "pinned": False,
                        "metadata": {"is_session_summary": True},
                        "source_description": "session_summary",
                    },
                    {
                        "uuid": "heartbeat-uuid",
                        "summary": "Heartbeat",
                        "content": "## Heartbeat: 20:56 EST\n\n### Orient",
                        "pinned": False,
                        "metadata": {},
                        "source_description": "learning",
                    },
                ]
            ),
        ):
            result = await build_reference_toon_index(MemoryScope.PROJECT, "portfolio-ai")

        assert result == [
            (
                "good-uuid",
                "Service scripts",
                "**Service Scripts**: Use rebuild.sh for frontend changes.",
                False,
            )
        ]
