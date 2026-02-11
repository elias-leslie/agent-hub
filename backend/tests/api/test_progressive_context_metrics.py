"""Tests for progressive-context endpoint metrics tracking.

Verifies that GET /progressive-context records usage metrics when
session_id or external_id are provided — closing the feedback loop
for non-completion-API callers (hooks, CLI tools).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.memory_agent_handlers import build_progressive_context_response
from app.services.memory.context_builder import ProgressiveContext
from app.services.memory.service import MemoryScope, MemorySearchResult, MemorySource


def _make_context(uuids: list[str]) -> ProgressiveContext:
    """Build a ProgressiveContext with mandates having given UUIDs."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return ProgressiveContext(
        mandates=[
            MemorySearchResult(
                uuid=u, content=f"content-{u}", source=MemorySource.SYSTEM,
                relevance_score=1.0, created_at=now, facts=[],
            )
            for u in uuids
        ],
        total_tokens=100,
    )


# Lazy imports inside build_progressive_context_response resolve from source modules.
# Top-level imports (build_reference_episodes, etc.) are bound in the handler module.
_SRC = "app.services.memory"
_HANDLER = "app.api.memory_agent_handlers"


@pytest.mark.unit
class TestProgressiveContextMetrics:
    """Tests for metrics tracking in build_progressive_context_response."""

    @pytest.mark.asyncio
    async def test_tracks_loaded_batch_always(self):
        """Loaded batch is tracked via usage_tracker even without session_id."""
        ctx = _make_context(["uuid-1", "uuid-2"])

        with (
            patch(f"{_SRC}.context_injector.build_progressive_context", new_callable=AsyncMock, return_value=ctx),
            patch(f"{_SRC}.context_injector.format_context_with_reference_index", return_value="formatted text"),
            patch(f"{_SRC}.context_injector.get_relevance_debug_info", return_value=None),
            patch(f"{_HANDLER}.build_reference_episodes", new_callable=AsyncMock, return_value=None),
            patch(f"{_SRC}.variants.assign_variant", return_value=MagicMock(value="BASELINE")),
            patch(f"{_SRC}.usage_tracker.track_loaded_batch", new_callable=AsyncMock) as mock_loaded,
            patch(f"{_SRC}.metrics_collector.record_injection_metrics") as mock_metrics,
            patch(f"{_HANDLER}.build_scoring_breakdown", return_value=None),
            patch(f"{_HANDLER}.build_budget_usage", return_value=None),
        ):
            await build_progressive_context_response(
                query="test query",
                scope=MemoryScope.GLOBAL,
                scope_id=None,
                debug=False,
                include_global=True,
                task_type=None,
            )

            mock_loaded.assert_called_once_with(["uuid-1", "uuid-2"])
            # No session_id or external_id → no PG metrics
            mock_metrics.assert_not_called()

    @pytest.mark.asyncio
    async def test_records_injection_metrics_with_session_id(self):
        """When session_id is provided, records injection metrics in PostgreSQL."""
        ctx = _make_context(["uuid-1"])

        with (
            patch(f"{_SRC}.context_injector.build_progressive_context", new_callable=AsyncMock, return_value=ctx),
            patch(f"{_SRC}.context_injector.format_context_with_reference_index", return_value="formatted"),
            patch(f"{_SRC}.context_injector.get_relevance_debug_info", return_value=None),
            patch(f"{_HANDLER}.build_reference_episodes", new_callable=AsyncMock, return_value=None),
            patch(f"{_SRC}.variants.assign_variant", return_value=MagicMock(value="BASELINE")),
            patch(f"{_SRC}.usage_tracker.track_loaded_batch", new_callable=AsyncMock),
            patch(f"{_SRC}.metrics_collector.record_injection_metrics") as mock_metrics,
            patch(f"{_HANDLER}.build_scoring_breakdown", return_value=None),
            patch(f"{_HANDLER}.build_budget_usage", return_value=None),
        ):
            await build_progressive_context_response(
                query="test query",
                scope=MemoryScope.PROJECT,
                scope_id="test-project",
                debug=False,
                include_global=True,
                task_type=None,
                session_id="session-abc",
                external_id="task-123",
                project_id="test-project",
            )

            mock_metrics.assert_called_once()
            metrics_arg = mock_metrics.call_args[0][0]
            assert metrics_arg.session_id == "session-abc"
            assert metrics_arg.external_id == "task-123"
            assert metrics_arg.project_id == "test-project"
            assert metrics_arg.memories_loaded == ["uuid-1"]
            assert metrics_arg.mandates_count == 1

    @pytest.mark.asyncio
    async def test_records_injection_metrics_with_external_id_only(self):
        """external_id alone is sufficient to trigger metrics recording."""
        ctx = _make_context(["uuid-1"])

        with (
            patch(f"{_SRC}.context_injector.build_progressive_context", new_callable=AsyncMock, return_value=ctx),
            patch(f"{_SRC}.context_injector.format_context_with_reference_index", return_value="formatted"),
            patch(f"{_SRC}.context_injector.get_relevance_debug_info", return_value=None),
            patch(f"{_HANDLER}.build_reference_episodes", new_callable=AsyncMock, return_value=None),
            patch(f"{_SRC}.variants.assign_variant", return_value=MagicMock(value="BASELINE")),
            patch(f"{_SRC}.usage_tracker.track_loaded_batch", new_callable=AsyncMock),
            patch(f"{_SRC}.metrics_collector.record_injection_metrics") as mock_metrics,
            patch(f"{_HANDLER}.build_scoring_breakdown", return_value=None),
            patch(f"{_HANDLER}.build_budget_usage", return_value=None),
        ):
            await build_progressive_context_response(
                query="test",
                scope=MemoryScope.GLOBAL,
                scope_id=None,
                debug=False,
                include_global=True,
                task_type=None,
                external_id="task-only",
            )

            mock_metrics.assert_called_once()
            metrics_arg = mock_metrics.call_args[0][0]
            assert metrics_arg.external_id == "task-only"
            assert metrics_arg.session_id is None

    @pytest.mark.asyncio
    async def test_no_loaded_uuids_skips_tracking(self):
        """Empty context with no loaded UUIDs skips track_loaded_batch."""
        ctx = ProgressiveContext(total_tokens=0)

        with (
            patch(f"{_SRC}.context_injector.build_progressive_context", new_callable=AsyncMock, return_value=ctx),
            patch(f"{_SRC}.context_injector.format_context_with_reference_index", return_value=""),
            patch(f"{_SRC}.context_injector.get_relevance_debug_info", return_value=None),
            patch(f"{_HANDLER}.build_reference_episodes", new_callable=AsyncMock, return_value=None),
            patch(f"{_SRC}.variants.assign_variant", return_value=MagicMock(value="BASELINE")),
            patch(f"{_SRC}.usage_tracker.track_loaded_batch", new_callable=AsyncMock) as mock_loaded,
            patch(f"{_HANDLER}.build_scoring_breakdown", return_value=None),
            patch(f"{_HANDLER}.build_budget_usage", return_value=None),
        ):
            await build_progressive_context_response(
                query="test",
                scope=MemoryScope.GLOBAL,
                scope_id=None,
                debug=False,
                include_global=True,
                task_type=None,
            )

            mock_loaded.assert_not_called()
