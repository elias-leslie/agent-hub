"""Tests for persona scheduler — compute_next_run and job execution logic."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.workflows.persona_scheduler import compute_next_run


class TestComputeNextRun:
    """Tests for next_run_at computation."""

    def test_at_future_returns_target(self):
        """'at' with a future datetime returns that datetime."""
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        result = compute_next_run("at", future)
        assert result is not None
        assert result > datetime.now(UTC)

    def test_at_past_returns_none(self):
        """'at' with a past datetime returns None."""
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        result = compute_next_run("at", past)
        assert result is None

    def test_every_from_scratch(self):
        """'every' with no last_run returns now + interval."""
        now = datetime.now(UTC)
        result = compute_next_run("every", "60000")  # 60 seconds
        assert result is not None
        assert result > now
        assert result < now + timedelta(seconds=120)

    def test_every_from_last_run(self):
        """'every' with last_run returns last_run + interval."""
        last = datetime.now(UTC) - timedelta(seconds=30)
        result = compute_next_run("every", "60000", last_run_at=last)
        assert result is not None
        # Should be last + 60s = ~30s from now
        expected = last + timedelta(milliseconds=60000)
        assert abs((result - expected).total_seconds()) < 2

    def test_every_catches_up_after_downtime(self):
        """'every' with stale last_run snaps to now + interval."""
        last = datetime.now(UTC) - timedelta(hours=2)
        result = compute_next_run("every", "60000", last_run_at=last)
        assert result is not None
        now = datetime.now(UTC)
        # Should be now + 60s since last + 60s is in the past
        assert result > now
        assert result < now + timedelta(seconds=120)

    def test_cron_basic(self):
        """'cron' returns next occurrence."""
        result = compute_next_run("cron", "*/5 * * * *")
        assert result is not None
        assert result > datetime.now(UTC)
        # Should be within 5 minutes
        assert result < datetime.now(UTC) + timedelta(minutes=6)

    def test_cron_with_timezone(self):
        """'cron' respects timezone."""
        result = compute_next_run("cron", "0 9 * * *", timezone="America/New_York")
        assert result is not None
        assert result > datetime.now(UTC)

    def test_cron_from_last_run(self):
        """'cron' with last_run computes from that base."""
        last = datetime.now(UTC) - timedelta(minutes=3)
        result = compute_next_run("cron", "*/5 * * * *", last_run_at=last)
        assert result is not None
        assert result > last

    def test_unknown_type_returns_none(self):
        """Unknown schedule_type returns None."""
        result = compute_next_run("unknown", "value")
        assert result is None


@pytest.mark.asyncio
async def test_execute_self_honing_skips_when_persona_or_supervisor_is_active():
    from app.workflows.persona_scheduler import _execute_self_honing

    job = SimpleNamespace(name="Nightly self-honing")

    with (
        patch(
            "app.workflows.persona_scheduler.query_active_sessions",
            new=AsyncMock(return_value=[{"session_id": "sess-1", "agent_slug": "persona"}]),
        ),
        patch(
            "app.workflows.persona_scheduler.run_honing_loop",
            new=AsyncMock(),
        ) as mock_honing,
    ):
        result = await _execute_self_honing(job)

    assert "Skipped" in result.output
    assert "persona" in result.output
    mock_honing.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_self_honing_runs_default_loop_and_reports_summary(tmp_path):
    from app.services.persona_improvement import PERSONA_IMPROVEMENT_SUITE_ID
    from app.workflows.persona_scheduler import _execute_self_honing
    from scripts.persona_benchmark_cases import get_persona_improvement_case_ids

    job = SimpleNamespace(name="Nightly self-honing")

    with (
        patch(
            "app.workflows.persona_scheduler.query_active_sessions",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.workflows.persona_scheduler._resolve_self_honing_models",
            new=AsyncMock(return_value=(["codex/gpt-5.4"], ["claude-sonnet-4-6"])),
        ),
        patch(
            "app.workflows.persona_scheduler.run_honing_loop",
            new=AsyncMock(
                return_value={
                    "honed": True,
                    "completed_iterations": 1,
                    "iterations": [
                        {
                            "benchmark_id": "persona-benchmark-1234abcd",
                            "failing_attempts": 0,
                        }
                    ],
                }
            ),
        ) as mock_honing,
        patch(
            "app.workflows.persona_scheduler._scheduled_self_honing_paths",
            return_value=(tmp_path / "work", tmp_path / "reports", tmp_path / "result.json"),
        ),
    ):
        result = await _execute_self_honing(job)

    assert "Self-honing completed" in result.output
    assert "honed=True" in result.output
    assert "persona-benchmark-1234abcd" in result.output
    mock_honing.assert_awaited_once()
    await_args = mock_honing.await_args
    assert await_args is not None
    assert await_args.kwargs["case_ids"] == get_persona_improvement_case_ids()
    assert await_args.kwargs["suite_id"] == PERSONA_IMPROVEMENT_SUITE_ID


@pytest.mark.asyncio
async def test_execute_memory_review_clamps_scheduled_batch_limit():
    from app.services.memory.review_agent import DEFAULT_BATCH_LIMIT
    from app.workflows.persona_scheduler import _execute_memory_review

    class FakeAsyncSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    job = SimpleNamespace(
        payload_message=json.dumps(
            {
                "batch_limit": DEFAULT_BATCH_LIMIT + 10,
                "cadence_days": 45,
                "reviewer_agent_slug": "memory-curator",
            }
        )
    )
    review_result = SimpleNamespace(
        status="completed",
        reviewed_count=1,
        needs_action_count=0,
        failed_count=0,
        reviewer_agent_slug="memory-curator",
        reviewer_model_id="codex/gpt-5.4",
        run_id="run-1",
        session_id="sess-1",
    )

    with (
        patch("app.db.async_session", return_value=FakeAsyncSession()),
        patch(
            "app.services.memory.review_agent.run_memory_review_batch",
            new=AsyncMock(return_value=review_result),
        ) as mock_review,
    ):
        result = await _execute_memory_review(job)

    assert "Memory review completed" in result.output
    mock_review.assert_awaited_once()
    await_args = mock_review.await_args
    assert await_args is not None
    assert await_args.kwargs["batch_limit"] == DEFAULT_BATCH_LIMIT
