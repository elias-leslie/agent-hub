"""Tests for progressive-context endpoint metrics tracking.

Verifies that GET /progressive-context records usage metrics when
session_id or external_id are provided — closing the feedback loop
for non-completion-API callers (hooks, CLI tools).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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


# Patch targets for handler's dependencies
_CTX_BUILDER = "app.api.memory_agent_context_builder"
_HANDLER = "app.api.memory_agent_handlers"


@pytest.mark.unit
class TestProgressiveContextMetrics:
    """Tests for metrics tracking in build_progressive_context_response."""

    @pytest.mark.asyncio
    async def test_tracks_loaded_batch_always(self):
        """Loaded batch is tracked via usage_tracker even without session_id."""
        ctx = _make_context(["uuid-1", "uuid-2"])

        with (
            patch(f"{_HANDLER}.build_progressive_context_with_variant", new_callable=AsyncMock, return_value=(ctx, "BASELINE")),
            patch(f"{_HANDLER}.format_context_with_continuity", new_callable=AsyncMock, return_value="formatted text"),
            patch(f"{_HANDLER}.track_and_record_metrics", new_callable=AsyncMock) as mock_track,
            patch("app.services.memory.context_injector.get_relevance_debug_info", return_value=None),
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

            # track_and_record_metrics is called with context and variant
            mock_track.assert_called_once()

    @pytest.mark.asyncio
    async def test_records_injection_metrics_with_session_id(self):
        """When session_id is provided, records injection metrics in PostgreSQL."""
        ctx = _make_context(["uuid-1"])

        with (
            patch(f"{_HANDLER}.build_progressive_context_with_variant", new_callable=AsyncMock, return_value=(ctx, "BASELINE")),
            patch(f"{_HANDLER}.format_context_with_continuity", new_callable=AsyncMock, return_value="formatted"),
            patch(f"{_HANDLER}.track_and_record_metrics", new_callable=AsyncMock) as mock_track,
            patch("app.services.memory.context_injector.get_relevance_debug_info", return_value=None),
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

            mock_track.assert_called_once()
            call_kwargs = mock_track.call_args[1]
            assert call_kwargs["session_id"] == "session-abc"
            assert call_kwargs["external_id"] == "task-123"
            assert call_kwargs["project_id"] == "test-project"

    @pytest.mark.asyncio
    async def test_records_injection_metrics_with_external_id_only(self):
        """external_id alone is sufficient to trigger metrics recording."""
        ctx = _make_context(["uuid-1"])

        with (
            patch(f"{_HANDLER}.build_progressive_context_with_variant", new_callable=AsyncMock, return_value=(ctx, "BASELINE")),
            patch(f"{_HANDLER}.format_context_with_continuity", new_callable=AsyncMock, return_value="formatted"),
            patch(f"{_HANDLER}.track_and_record_metrics", new_callable=AsyncMock) as mock_track,
            patch("app.services.memory.context_injector.get_relevance_debug_info", return_value=None),
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

            mock_track.assert_called_once()
            call_kwargs = mock_track.call_args[1]
            assert call_kwargs["external_id"] == "task-only"
            assert call_kwargs["session_id"] is None

    @pytest.mark.asyncio
    async def test_no_loaded_uuids_skips_tracking(self):
        """Empty context with no loaded UUIDs still calls track_and_record_metrics."""
        ctx = ProgressiveContext(total_tokens=0)

        with (
            patch(f"{_HANDLER}.build_progressive_context_with_variant", new_callable=AsyncMock, return_value=(ctx, "BASELINE")),
            patch(f"{_HANDLER}.format_context_with_continuity", new_callable=AsyncMock, return_value=""),
            patch(f"{_HANDLER}.track_and_record_metrics", new_callable=AsyncMock) as mock_track,
            patch("app.services.memory.context_injector.get_relevance_debug_info", return_value=None),
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

            # track_and_record_metrics is always called (it handles empty internally)
            mock_track.assert_called_once()
