"""Focused tests for query-relevant reference injection."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.context_builder import build_progressive_context
from app.services.memory.context_injector import format_progressive_context
from app.services.memory.context_injector_blocks_helpers import episode_to_result
from app.services.memory.context_profiles import CODEX_STARTUP_FULL_TAG
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
        assert context.guardrails[0].render_tier == "L2"
        assert context.guardrails[0].rendered_content == long_guardrail
        assert context.debug_info["tier_counts"] == {"L2": 2}
        assert context.debug_info["render_chars_saved"] == 0
        assert context.debug_info["memory_plan"][0]["uuid"] == "mandate-uuid"
        assert context.debug_info["memory_plan"][1]["tier"] == "L2"

    @pytest.mark.asyncio
    async def test_build_progressive_context_uses_compact_defaults_for_long_mandates(self) -> None:
        long_mandate = (
            "Use one canonical prompt layer for durable instructions, then keep dynamic state and examples "
            "in task-specific prompt variables so the runtime stays compact and easier to reason about."
        )
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(
                    return_value=(
                        [
                            MemorySearchResult(
                                uuid="mandate-uuid",
                                content=long_mandate,
                                summary="Keep durable instructions canonical and compact.",
                                source=MemorySource.SYSTEM,
                                relevance_score=1.0,
                                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                                facts=[],
                            )
                        ],
                        [],
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
                query="Unrelated query that should not force expansion.",
                scope=MemoryScope.GLOBAL,
            )

        assert context.mandates[0].render_tier == "L2"
        assert context.mandates[0].rendered_content == long_mandate

    @pytest.mark.asyncio
    async def test_build_progressive_context_codex_startup_promotes_tagged_items(self) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(
                    return_value=(
                        [
                            MemorySearchResult(
                                uuid="later-uuid",
                                content=(
                                    "Keep startup guidance concise, verify commands against the live environment, "
                                    "and avoid acting on a summary when the full rule text could change behavior."
                                ),
                                summary="Generic startup guidance.",
                                source=MemorySource.SYSTEM,
                                relevance_score=0.8,
                                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                                facts=[],
                            ),
                            MemorySearchResult(
                                uuid="critical-uuid",
                                content="Use st memory get before acting when a summary could change behavior.",
                                summary="Expand exact rules first.",
                                source=MemorySource.SYSTEM,
                                relevance_score=0.6,
                                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                                facts=[],
                                tags=[CODEX_STARTUP_FULL_TAG],
                            ),
                        ],
                        [],
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
                query="General startup guidance.",
                scope=MemoryScope.GLOBAL,
                consumer_profile="codex_startup",
            )

        assert [item.uuid for item in context.mandates] == ["critical-uuid", "later-uuid"]
        assert context.mandates[0].render_tier == "L2"
        assert context.mandates[0].render_reason == "consumer_profile_tag"
        assert context.mandates[0].rendered_content == context.mandates[0].content
        assert context.mandates[1].render_tier == "L2"
        assert context.debug_info["consumer_profile"] == "codex_startup"

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

    @pytest.mark.asyncio
    async def test_build_progressive_context_skips_query_selected_references_for_heartbeat(self) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        selector = AsyncMock(
            return_value=[
                _reference_result(
                    "f2ae2668-da26-46e1-b499-ffac6141e377",
                    "**Session Surfaces**: Existing ref.",
                ).model_dump()
            ]
        )

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=([], [], [])),
            ),
            patch(
                "app.services.memory.context_builder.get_query_relevant_references_as_search_results",
                new=selector,
            ),
            patch(
                "app.services.memory.context_builder.get_memory_settings",
                new=AsyncMock(return_value=settings),
            ),
        ):
            context = await build_progressive_context(
                query="Run the heartbeat now and review dynamic sections.",
                scope=MemoryScope.PROJECT,
                scope_id="agent-hub",
                task_type="heartbeat",
            )

        selector.assert_not_awaited()
        assert context.reference == []
        assert context.debug_info["reference_count"] == 0

    @pytest.mark.asyncio
    async def test_build_progressive_context_skips_references_when_disabled(self) -> None:
        auto_reference = _reference_result(
            "f2ae2668-da26-46e1-b499-ffac6141e377",
            "**Session Surfaces**: Existing ref.",
        )
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=([], [], [auto_reference])),
            ),
            patch(
                "app.services.memory.context_builder.get_query_relevant_references_as_search_results",
                new=AsyncMock(return_value=[auto_reference.model_dump()]),
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
                include_references=False,
            )

        assert context.reference == []
        assert context.debug_info["reference_count"] == 0

    @pytest.mark.asyncio
    async def test_build_progressive_context_applies_variant_reference_limits(self) -> None:
        refs = [
            _reference_result("ref-1-0000-0000-0000-000000000001", "**Ref 1**", 0.45),
            _reference_result("ref-2-0000-0000-0000-000000000002", "**Ref 2**", 0.82),
            _reference_result("ref-3-0000-0000-0000-000000000003", "**Ref 3**", 0.71),
            _reference_result("ref-4-0000-0000-0000-000000000004", "**Ref 4**", 0.93),
        ]
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=([], [], refs)),
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
            minimal = await build_progressive_context(
                query="reference selection",
                scope=MemoryScope.PROJECT,
                scope_id="agent-hub",
                variant="MINIMAL",
            )
            aggressive = await build_progressive_context(
                query="reference selection",
                scope=MemoryScope.PROJECT,
                scope_id="agent-hub",
                variant="AGGRESSIVE",
            )

        assert [item.uuid for item in minimal.reference] == [
            "ref-4-0000-0000-0000-000000000004",
            "ref-2-0000-0000-0000-000000000002",
        ]
        assert [item.uuid for item in aggressive.reference] == [item.uuid for item in refs]

    def test_format_progressive_context_renders_selected_references_without_passive_index(self) -> None:
        context = type("Ctx", (), {})()
        context.mandates = []
        context.guardrails = []
        context.reference = [
            _reference_result(
                "f2ae2668-da26-46e1-b499-ffac6141e377",
                "**Session Surfaces**: Use st sessions ownership for normalized lane truth.",
            )
        ]

        result = format_progressive_context(context, include_citations=True)

        assert "open the exact episode with `st memory get <uuid8>` before acting" in result
        assert "## Selected References" in result
        assert "Likely direct fits for this task" in result
        assert "[R:f2ae2668]" in result
        assert "## Reference Index" not in result
