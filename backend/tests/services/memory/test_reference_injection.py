"""Focused tests for query-relevant reference injection."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.context_builder import build_progressive_context
from app.services.memory.context_injector import format_progressive_context
from app.services.memory.context_injector_blocks_helpers import episode_to_result
from app.services.memory.context_injector_queries import (
    get_query_relevant_references_as_search_results,
)
from app.services.memory.context_profiles import CODEX_STARTUP_FULL_TAG
from app.services.memory.memory_models import MemoryApplicability
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
                "review_status": "clean",
            }
        )

        assert result is not None
        assert result.tags == []
        assert result.review_status == "clean"

    @pytest.mark.asyncio
    async def test_query_relevant_reference_payload_preserves_trigger_hints(self) -> None:
        row = {
            "id": "8ac96de8-a4e4-4ba7-a7a2-b4a3162e8eb5",
            "content": "**Runtime Proxmox**: Keep integration read-only.",
            "summary": "runtime proxmox read-only api",
            "scope": "global",
            "tier": 3,
            "context_kind": "reference",
            "applicability": {},
            "trigger_task_types": ["devops", "verification"],
            "trigger_phases": ["verification"],
            "relevance_score": 0.81,
            "created_at": datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
        }

        with patch(
            "app.services.memory.context_injector_queries.get_query_relevant_references",
            new=AsyncMock(return_value=[row]),
        ):
            payloads = await get_query_relevant_references_as_search_results(
                "Inspect runtime health",
                [(MemoryScope.GLOBAL, None)],
            )

        assert payloads[0]["trigger_task_types"] == ["devops", "verification"]
        assert payloads[0]["trigger_phases"] == ["verification"]

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
    async def test_build_progressive_context_keeps_explicitly_targeted_reference_when_legacy_tags_do_not_match(self) -> None:
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
                        [],
                        [],
                        [
                            MemorySearchResult(
                                uuid="persona-targeted",
                                content="Use st persona first for persona work.",
                                summary="Persona CLI first",
                                source=MemorySource.SYSTEM,
                                relevance_score=1.0,
                                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                                facts=[],
                                applicability=MemoryApplicability(agent_slugs=["persona"]),
                            ),
                            MemorySearchResult(
                                uuid="legacy-tagged",
                                content="Use debugger-only workflow.",
                                summary="Debugger reference",
                                source=MemorySource.SYSTEM,
                                relevance_score=0.8,
                                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                                facts=[],
                                tags=["debugger-relevant"],
                            ),
                        ],
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
                query="persona tooling",
                scope=MemoryScope.GLOBAL,
                memory_config={
                    "injection_enabled": True,
                    "include_mandates": False,
                    "include_guardrails": False,
                    "include_references": True,
                    "reference_index_enabled": True,
                    "audience_tags": ["persona-relevant"],
                    "exclude_tags": [],
                    "exclude_memory_uuids": [],
                },
                include_mandates=False,
                include_guardrails=False,
                consumer_profile="agent_preview",
                consumer_agent_slug="persona",
                consumer_tags=["persona-relevant"],
            )

        assert [item.uuid for item in context.reference] == ["persona-targeted"]

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
        assert context.mandates[1].render_tier == "L0"
        assert context.mandates[1].render_reason == "policy_summary"
        assert context.mandates[1].rendered_content == "Generic startup guidance."
        assert context.debug_info["consumer_profile"] == "codex_startup"

    @pytest.mark.asyncio
    async def test_build_progressive_context_operator_uses_generic_policy_summary_reason(self) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(
                    return_value=(
                        [
                            MemorySearchResult(
                                uuid="operator-uuid",
                                content="Use preview before explaining effective prompt.",
                                summary="Prompt preview first.",
                                source=MemorySource.SYSTEM,
                                relevance_score=0.8,
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
                query="Explain prompt preview flow.",
                scope=MemoryScope.PROJECT,
                scope_id="agent-hub",
                consumer_profile="agent_operator",
            )

        assert context.mandates[0].render_tier == "L0"
        assert context.mandates[0].render_reason == "policy_summary"

    @pytest.mark.asyncio
    async def test_build_progressive_context_codex_startup_compacts_before_policy_limit(self) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        mandates = [
            MemorySearchResult(
                uuid=f"m-{idx:02d}",
                content=f"Mandate {idx}: keep startup concise and reliable.",
                summary=f"Mandate {idx}.",
                source=MemorySource.SYSTEM,
                relevance_score=1.0 - (idx * 0.01),
                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                facts=[],
            )
            for idx in range(40)
        ]
        guardrails = [
            MemorySearchResult(
                uuid=f"g-{idx:02d}",
                content=f"Guardrail {idx}: avoid unsafe startup behavior.",
                summary=f"Guardrail {idx}.",
                source=MemorySource.SYSTEM,
                relevance_score=1.0 - (idx * 0.01),
                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                facts=[],
            )
            for idx in range(10)
        ]

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=(mandates, guardrails, [])),
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

        assert len(context.mandates) == 28
        assert len(context.guardrails) == 6
        assert context.mandates[0].uuid == "m-00"
        assert context.mandates[-1].uuid == "m-27"
        assert context.guardrails[0].uuid == "g-00"
        assert context.guardrails[-1].uuid == "g-05"

    @pytest.mark.asyncio
    async def test_build_progressive_context_agent_coding_uses_compact_policy_profile(self) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        mandates = [
            MemorySearchResult(
                uuid=f"m-{idx:02d}",
                content=f"Mandate {idx}: keep coding context focused and durable.",
                summary=f"Mandate {idx}.",
                source=MemorySource.SYSTEM,
                relevance_score=1.0 - (idx * 0.01),
                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                facts=[],
            )
            for idx in range(25)
        ]
        guardrails = [
            MemorySearchResult(
                uuid=f"g-{idx:02d}",
                content=f"Guardrail {idx}: avoid broad context poison.",
                summary=f"Guardrail {idx}.",
                source=MemorySource.SYSTEM,
                relevance_score=1.0 - (idx * 0.01),
                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                facts=[],
            )
            for idx in range(8)
        ]

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=(mandates, guardrails, [])),
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
                query="Fix one failing backend test.",
                scope=MemoryScope.GLOBAL,
                consumer_profile="agent_coding",
            )

        assert len(context.mandates) == 16
        assert len(context.guardrails) == 4
        assert context.mandates[0].render_tier == "L0"
        assert context.guardrails[0].render_tier == "L0"
        assert context.debug_info["consumer_profile"] == "agent_coding"

    @pytest.mark.asyncio
    async def test_build_progressive_context_promptops_uses_tighter_policy_profile(self) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        mandates = [
            MemorySearchResult(
                uuid=f"m-{idx:02d}",
                content=f"Promptops mandate {idx}.",
                summary=f"Mandate {idx}.",
                source=MemorySource.SYSTEM,
                relevance_score=1.0,
                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                facts=[],
            )
            for idx in range(20)
        ]
        guardrails = [
            MemorySearchResult(
                uuid=f"g-{idx:02d}",
                content=f"Promptops guardrail {idx}.",
                summary=f"Guardrail {idx}.",
                source=MemorySource.SYSTEM,
                relevance_score=1.0,
                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                facts=[],
            )
            for idx in range(8)
        ]

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=(mandates, guardrails, [])),
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
                query="Review prompt routing.",
                scope=MemoryScope.GLOBAL,
                consumer_profile="agent_promptops",
            )

        assert len(context.mandates) == 14
        assert len(context.guardrails) == 4
        assert context.debug_info["mandates_count"] == 14

    @pytest.mark.asyncio
    async def test_build_progressive_context_prioritizes_clean_reviewed_policies(self) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        mandates = [
            MemorySearchResult(
                uuid=f"needs-{idx}",
                content=f"Needs action mandate {idx}.",
                summary=f"Needs {idx}.",
                source=MemorySource.SYSTEM,
                relevance_score=1.0,
                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                facts=[],
                review_status="needs_action",
            )
            for idx in range(4)
        ] + [
            MemorySearchResult(
                uuid=f"clean-{idx}",
                content=f"Clean mandate {idx}.",
                summary=f"Clean {idx}.",
                source=MemorySource.SYSTEM,
                relevance_score=0.4,
                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                facts=[],
                review_status="clean",
            )
            for idx in range(4)
        ]

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=(mandates, [], [])),
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
                query="General chat.",
                scope=MemoryScope.GLOBAL,
                consumer_profile="agent_general",
            )

        assert [item.uuid for item in context.mandates[:4]] == [
            "clean-0",
            "clean-1",
            "clean-2",
            "clean-3",
        ]
        assert len(context.mandates) == 6

    @pytest.mark.asyncio
    async def test_build_progressive_context_compacts_before_policy_limit(self) -> None:
        full = (
            "Use st check for every repository quality gate before closeout. "
            "Never run raw pytest, Vitest, Ruff, TSC, SQLFluff, Squawk, or legacy dt."
        )
        compact = "Use st check for all repo gates. Never run raw pytest/Vitest/Ruff/TSC."
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        mandates = [
            MemorySearchResult(
                uuid=f"compact-{idx}",
                content=full,
                compact_content=compact,
                summary=f"Gate {idx}.",
                source=MemorySource.SYSTEM,
                relevance_score=1.0,
                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                facts=[],
                review_status="clean",
            )
            for idx in range(10)
        ]

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=(mandates, [], [])),
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
                query="Run quality gates.",
                scope=MemoryScope.GLOBAL,
                consumer_profile="agent_general",
            )

        assert len(context.mandates) == 6
        assert all(item.rendered_content == compact for item in context.mandates)
        assert context.debug_info["render_chars_saved"] > 0

    @pytest.mark.asyncio
    async def test_build_progressive_context_query_selected_refs_respect_triggers_and_applicability(self) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        targeted = _reference_result(
            "b54378e2-d12e-4510-bfad-59eba8e7350a",
            "**Session Events Memory Summary**: Operator-only reference.",
        )
        targeted.applicability.consumer_profiles = ["agent_operator"]
        frontend_only = _reference_result(
            "49372f37-2d06-414d-bb4d-f97c53224199",
            "**SF Browser Canonical Interface**: Frontend-only reference.",
        )
        targeted_payload = targeted.model_dump()
        frontend_payload = frontend_only.model_dump()
        frontend_payload["context_kind"] = "capability"
        frontend_payload["trigger_task_types"] = ["frontend"]

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=([], [], [])),
            ),
            patch(
                "app.services.memory.context_builder.get_query_relevant_references_as_search_results",
                new=AsyncMock(
                    return_value=[targeted_payload, frontend_payload]
                ),
            ),
            patch(
                "app.services.memory.context_builder.get_memory_settings",
                new=AsyncMock(return_value=settings),
            ),
        ):
            context = await build_progressive_context(
                query="Answer user question about feature",
                scope=MemoryScope.GLOBAL,
                consumer_profile="agent_general",
                task_type=None,
            )

        assert context.reference == []
        assert context.reference_index == []

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
    async def test_build_progressive_context_allows_query_selected_references_for_heartbeat_when_enabled(
        self,
    ) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        selector = AsyncMock(
            return_value=[
                _reference_result(
                    "f2ae2668-da26-46e1-b499-ffac6141e377",
                    "**Session Surfaces**: Use st sessions ownership for normalized lane truth.",
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
                memory_config={"query_reference_selection_enabled": True},
            )

        selector.assert_awaited_once()
        assert [item.uuid for item in context.reference] == [
            "f2ae2668-da26-46e1-b499-ffac6141e377"
        ]
        assert context.debug_info["reference_count"] == 1

    @pytest.mark.asyncio
    async def test_build_progressive_context_injects_query_selected_references_for_wake(self) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        selector = AsyncMock(
            return_value=[
                _reference_result(
                    "f2ae2668-da26-46e1-b499-ffac6141e377",
                    "**st agents preview**: Use `st agents preview <slug>` for agent runtime preview.",
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
                query="Inspect agent preview and command surfaces before broad search.",
                scope=MemoryScope.PROJECT,
                scope_id="agent-hub",
                task_type="wake",
            )

        selector.assert_awaited_once()
        assert [item.uuid for item in context.reference] == [
            "f2ae2668-da26-46e1-b499-ffac6141e377",
        ]
        assert context.debug_info["reference_count"] == 1

    @pytest.mark.asyncio
    async def test_build_progressive_context_skips_query_selected_refs_for_general_profile_by_default(
        self,
    ) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        selector = AsyncMock(
            return_value=[
                _reference_result(
                    "f2ae2668-da26-46e1-b499-ffac6141e377",
                    "**Prompt Surfaces**: Example reference that should stay out of chat.",
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
                query="Say ok.",
                scope=MemoryScope.PROJECT,
                scope_id="agent-hub",
                consumer_profile="agent_general",
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

    @pytest.mark.asyncio
    async def test_build_progressive_context_scores_wake_references_by_variant(self) -> None:
        settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        refs = [
            MemorySearchResult(
                uuid="high-score-ref",
                content="Recent high-signal wake guidance.",
                source=MemorySource.SYSTEM,
                relevance_score=0.85,
                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                facts=[],
                loaded_count=12,
                referenced_count=9,
                confidence=90.0,
            ),
            MemorySearchResult(
                uuid="borderline-ref",
                content="Borderline wake guidance that should only survive looser variants.",
                source=MemorySource.SYSTEM,
                relevance_score=0.25,
                created_at=datetime(2026, 3, 7, 20, 55, tzinfo=UTC),
                facts=[],
                loaded_count=0,
                referenced_count=0,
                confidence=55.0,
            ),
        ]

        selector = AsyncMock(return_value=[])

        with (
            patch(
                "app.services.memory.context_builder.fetch_all_episodes",
                new=AsyncMock(return_value=([], [], refs)),
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
            minimal = await build_progressive_context(
                query="wake benchmark reference scoring",
                scope=MemoryScope.PROJECT,
                scope_id="agent-hub",
                task_type="wake",
                variant="MINIMAL",
            )
            aggressive = await build_progressive_context(
                query="wake benchmark reference scoring",
                scope=MemoryScope.PROJECT,
                scope_id="agent-hub",
                task_type="wake",
                variant="AGGRESSIVE",
            )

        assert selector.await_count == 2
        assert [item.uuid for item in minimal.reference] == ["high-score-ref"]
        assert [item.uuid for item in aggressive.reference] == [
            "high-score-ref",
            "borderline-ref",
        ]

    def test_format_progressive_context_renders_selected_references_without_passive_index(self) -> None:
        context = SimpleNamespace(
            mandates=[],
            guardrails=[],
            reference=[
            _reference_result(
                "f2ae2668-da26-46e1-b499-ffac6141e377",
                "**Session Surfaces**: Use st sessions ownership for normalized lane truth.",
            )
            ],
        )

        result = format_progressive_context(context, include_citations=True)

        assert "open the exact episode with `st memory get <uuid8>` before acting" in result
        assert "## Selected References" in result
        assert "Likely direct fits for this task" in result
        assert "[R:f2ae2668]" in result
        assert "## Reference Index" not in result
