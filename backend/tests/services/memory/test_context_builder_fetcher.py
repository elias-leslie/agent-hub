"""Tests for fetch_all_episodes pinned-memory behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.context_builder import build_progressive_context, fetch_all_episodes
from app.services.memory.context_injector_blocks_helpers import mandate_episode_to_result
from app.services.memory.service import MemoryScope, MemorySearchResult, MemorySource
from app.services.memory.settings import MemorySettingsDTO


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


def _settings() -> MemorySettingsDTO:
    return MemorySettingsDTO(
        enabled=True,
        budget_enabled=True,
        total_budget=3500,
        max_mandates=0,
        max_guardrails=0,
        reference_index_enabled=True,
        continuity_enabled=True,
        continuity_max_sessions=5,
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
                "app.services.memory.context_builder.get_mandates",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.memory.context_builder.get_guardrails",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.memory.context_builder.get_auto_inject_references_as_search_results",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.memory.context_builder.get_pinned_episodes_as_search_results",
                new=AsyncMock(
                    side_effect=lambda tier, scope, scope_id, **_kwargs: [pinned_reference]
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
                "app.services.memory.context_builder.get_mandates",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.memory.context_builder.get_guardrails",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.memory.context_builder.get_auto_inject_references_as_search_results",
                new=AsyncMock(return_value=[duplicate_reference]),
            ),
            patch(
                "app.services.memory.context_builder.get_pinned_episodes_as_search_results",
                new=AsyncMock(
                    side_effect=lambda tier, scope, scope_id, **_kwargs: [duplicate_reference]
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

    @pytest.mark.asyncio
    async def test_fetch_all_episodes_threads_shared_session_to_all_fetchers(self) -> None:
        db = object()
        mandates = AsyncMock(return_value=[])
        guardrails = AsyncMock(return_value=[])
        auto_references = AsyncMock(return_value=[])
        pinned = AsyncMock(return_value=[])
        triggered = AsyncMock(return_value=[])
        phase_triggered = AsyncMock(return_value=[])

        with (
            patch("app.services.memory.context_builder.get_mandates", new=mandates),
            patch("app.services.memory.context_builder.get_guardrails", new=guardrails),
            patch(
                "app.services.memory.context_builder.get_auto_inject_references_as_search_results",
                new=auto_references,
            ),
            patch(
                "app.services.memory.context_builder.get_pinned_episodes_as_search_results",
                new=pinned,
            ),
            patch(
                "app.services.memory.context_builder.get_triggered_references_as_search_results",
                new=triggered,
            ),
            patch(
                "app.services.memory.context_builder.get_phase_triggered_references_as_search_results",
                new=phase_triggered,
            ),
        ):
            await fetch_all_episodes(
                [(MemoryScope.PROJECT, "agent-hub"), (MemoryScope.GLOBAL, None)],
                include_mandates=True,
                include_guardrails=True,
                include_references=True,
                task_type="implementation",
                phase="verification",
                db=db,
            )

        for fetcher in (mandates, guardrails, auto_references, pinned, triggered, phase_triggered):
            assert fetcher.await_args_list
            assert all(call.kwargs["db"] is db for call in fetcher.await_args_list)

    @pytest.mark.asyncio
    async def test_build_progressive_context_uses_one_owned_session(self) -> None:
        class SessionContext:
            def __init__(self) -> None:
                self.session = object()
                self.enter_count = 0
                self.exit_count = 0

            async def __aenter__(self) -> object:
                self.enter_count += 1
                return self.session

            async def __aexit__(self, *_args: object) -> None:
                self.exit_count += 1

        contexts: list[SessionContext] = []

        def session_factory() -> SessionContext:
            context = SessionContext()
            contexts.append(context)
            return context

        fetch_all = AsyncMock(return_value=([], [], []))
        get_settings = AsyncMock(return_value=_settings())
        resolve_limits = AsyncMock(return_value=(0, 0, 0))

        with (
            patch("app.services.memory.context_builder.async_session", side_effect=session_factory),
            patch("app.services.memory.context_builder.get_memory_settings", new=get_settings),
            patch("app.services.memory.context_builder.fetch_all_episodes", new=fetch_all),
            patch("app.services.memory.context_builder.resolve_policy_limits", new=resolve_limits),
        ):
            await build_progressive_context(
                query="startup context",
                scope=MemoryScope.PROJECT,
                scope_id="agent-hub",
                include_references=False,
            )

        assert len(contexts) == 1
        assert contexts[0].enter_count == 1
        assert contexts[0].exit_count == 1
        assert get_settings.await_args is not None
        assert fetch_all.await_args is not None
        assert resolve_limits.await_args is not None
        assert get_settings.await_args.args == (contexts[0].session,)
        assert fetch_all.await_args.kwargs["db"] is contexts[0].session
        assert resolve_limits.await_args.args[-1] is contexts[0].session

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
