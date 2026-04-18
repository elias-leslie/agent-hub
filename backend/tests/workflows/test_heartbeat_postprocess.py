"""Tests for heartbeat post-processing — summaries and format validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows._heartbeat_postprocess import (
    _build_performance_observation,
    _detect_followup_reason,
    _ensure_session_summary,
    _extract_synthetic_summary,
    _maybe_review_completion,
    _validate_heartbeat_format,
    postprocess_heartbeat,
)


def _make_result(**overrides):
    """Create a mock CompletionInternalResult."""
    defaults = {
        "content": (
            "HEARTBEAT_OK — [[P:started:reviewing permitted projects]] "
            "[[P:decision:no follow-up dispatch required after verification]] "
            "[[S:completed:Reviewed the heartbeat state and confirmed no further action was needed.]]"
        ),
        "session_id": "sess-test-123",
        "turns": 3,
        "tool_calls_count": 5,
        "status": "success",
        "error": None,
        "model": "codex/gpt-5.4",
        "model_used": None,
        "input_tokens": 1200,
        "output_tokens": 400,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestExtractSyntheticSummary:
    """Tests for _extract_synthetic_summary."""

    def test_heartbeat_ok_prefix(self):
        summary = _extract_synthetic_summary("HEARTBEAT_OK — All systems normal.")
        assert summary == "All systems normal."

    def test_heartbeat_action_prefix(self):
        summary = _extract_synthetic_summary("HEARTBEAT_ACTION - Deployed fix to staging.")
        assert summary == "Deployed fix to staging."

    def test_long_content_truncated(self):
        long_text = "HEARTBEAT_OK — " + "A" * 200
        summary = _extract_synthetic_summary(long_text)
        assert len(summary) <= 123  # 120 + "..."
        assert summary.endswith("...")

    def test_fallback_no_prefix(self):
        summary = _extract_synthetic_summary("Something happened without prefix.")
        assert summary == "Something happened without prefix."

    def test_empty_content(self):
        assert _extract_synthetic_summary("") == ""
        assert _extract_synthetic_summary("   ") == ""

    def test_prefix_only_returns_lowercase(self):
        summary = _extract_synthetic_summary("HEARTBEAT_OK")
        assert summary == "heartbeat ok"

    def test_sentence_boundary_extraction(self):
        content = "HEARTBEAT_OK — First sentence. Second sentence with more detail."
        summary = _extract_synthetic_summary(content)
        assert summary == "First sentence."

    def test_filters_command_tail_from_heartbeat_summary(self):
        content = (
            "HEARTBEAT_ACTION — [[P:tested:dt -q -d passes clean - biome OK, tsc OK, zero errors]] "
            "Type checks pass. Now commit via `/commit_it`."
        )

        summary = _extract_synthetic_summary(content)

        assert "/commit_it" not in summary
        assert "passes clean" in summary or "Type checks pass." in summary


class TestValidateHeartbeatFormat:
    """Tests for _validate_heartbeat_format."""

    def test_heartbeat_ok_format(self):
        status, compliant, summary_ok, progress_ok = _validate_heartbeat_format(
            "HEARTBEAT_OK — [[P:started:reviewing queue]] "
            "[[P:decision:no action required]] "
            "[[S:completed:Everything fine.]]"
        )
        assert status == "success"
        assert compliant is True
        assert summary_ok is True
        assert progress_ok is True

    def test_heartbeat_action_format(self):
        status, compliant, summary_ok, progress_ok = _validate_heartbeat_format(
            "HEARTBEAT_ACTION — [[P:started:repairing queue state]] "
            "[[P:tested:validation passed after the repair]] "
            "[[S:completed:Deployed fix.]]"
        )
        assert status == "action"
        assert compliant is True
        assert summary_ok is True
        assert progress_ok is True

    def test_detached_rebuild_closeout_is_compliant(self):
        status, compliant, summary_ok, progress_ok = _validate_heartbeat_format(
            "HEARTBEAT_ACTION — Detached Agent Hub rebuild queued as sf-rebuild-agent-hub.service. "
            "Post-restart verification is deferred to a fresh session.\n"
            "[[P:started:ending the heartbeat after queueing a detached Agent Hub rebuild]]\n"
            "[[P:decision:queued detached Agent Hub rebuild as sf-rebuild-agent-hub.service "
            "and ended before post-restart verification]]\n"
            "[[S:partial:Queued detached Agent Hub rebuild; a fresh post-restart session "
            "must verify health and task completion.]]"
        )
        assert status == "action"
        assert compliant is True
        assert summary_ok is True
        assert progress_ok is True

    def test_missing_summary_tag_is_noncompliant(self):
        status, compliant, summary_ok, progress_ok = _validate_heartbeat_format(
            "HEARTBEAT_OK — [[P:started:reviewing queue]] [[P:decision:no action required]]"
        )
        assert status == "success"
        assert compliant is False
        assert summary_ok is False
        assert progress_ok is True

    def test_missing_progress_tags_is_noncompliant(self):
        status, compliant, summary_ok, progress_ok = _validate_heartbeat_format(
            "HEARTBEAT_OK — Everything fine. [[S:completed:Everything fine.]]"
        )
        assert status == "success"
        assert compliant is False
        assert summary_ok is True
        assert progress_ok is False

    def test_noncompliant_format(self):
        status, compliant, summary_ok, progress_ok = _validate_heartbeat_format("I did some stuff today.")
        assert status == "success"
        assert compliant is False
        assert summary_ok is False
        assert progress_ok is False

    def test_empty_content(self):
        status, compliant, summary_ok, progress_ok = _validate_heartbeat_format("")
        assert status == "success"
        assert compliant is False
        assert summary_ok is False
        assert progress_ok is False

    def test_none_content(self):
        status, compliant, summary_ok, progress_ok = _validate_heartbeat_format(None)
        assert status == "success"
        assert compliant is False
        assert summary_ok is False
        assert progress_ok is False


class TestDetectFollowupReason:
    def test_detects_actionable_cleanup_after_heartbeat_ok(self) -> None:
        reason = _detect_followup_reason(
            "HEARTBEAT_OK — Routine sweep complete.",
            "\n<cleanup_status>\nACTIONABLE-CLEANUP[1]\n- agent-hub | finalize | task-123\n</cleanup_status>",
            "",
        )

        assert reason == "cleanup_actionable"

    def test_detects_stale_running_task_after_heartbeat_ok(self) -> None:
        reason = _detect_followup_reason(
            "HEARTBEAT_OK — Routine sweep complete.",
            "",
            '\n<workstream_inventory>\n- task-1 | state=stale_running_task | next=manage_tasks(action="reconcile")\n</workstream_inventory>',
        )

        assert reason == "stale_running_task"

    def test_skips_followup_when_heartbeat_already_reported_action(self) -> None:
        reason = _detect_followup_reason(
            "HEARTBEAT_ACTION — Reconciled stale lane.",
            "\n<cleanup_status>\nACTIONABLE-CLEANUP[1]\n</cleanup_status>",
            "",
        )

        assert reason is None


class TestBuildPerformanceObservation:
    def test_returns_none_for_clean_heartbeat(self) -> None:
        observation = _build_performance_observation(
            result=_make_result(),
            format_ok=True,
            summary_tag_ok=True,
            progress_tag_ok=True,
            followup_reason=None,
            completion_review=MagicMock(used=True, decision="complete", reason="Looks good."),
        )

        assert observation is None

    def test_captures_format_followup_and_review_issues(self) -> None:
        observation = _build_performance_observation(
            result=_make_result(content="Routine sweep complete.", error=None),
            format_ok=False,
            summary_tag_ok=False,
            progress_tag_ok=False,
            followup_reason="cleanup_actionable",
            completion_review=MagicMock(
                used=True,
                decision="continue",
                reason="A quiet lane still needs one more pass.",
            ),
        )

        assert observation is not None
        assert observation["feedback_type"] == "friction"
        assert observation["outcome"] == "partial"
        assert "missing HEARTBEAT_OK/HEARTBEAT_ACTION prefix" in observation["content"]
        assert "post-run residue detected: cleanup_actionable" in observation["content"]
        assert "completion review requested continue" in observation["content"]


class TestEnsureSessionSummary:
    """Tests for _ensure_session_summary."""

    @pytest.mark.asyncio
    async def test_inline_tags_stored(self):
        """Verifies [[S:...]] tags are parsed and stored."""
        content = "HEARTBEAT_OK [[S:completed:All checks passed]]"
        mock_db = AsyncMock()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.api.complete.citation_tracker.track_inline_summaries",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_track,
        ):
            result = await _ensure_session_summary("sess-1", content)

        assert result is True
        mock_track.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_synthetic_fallback_when_no_tags(self):
        """Verifies synthetic summary when no [[S:...]] tags present."""
        content = "HEARTBEAT_OK — Routine check completed."
        mock_db = AsyncMock()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.api.complete.citation_tracker.track_inline_summaries",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.services.memory.summary_generator.generate_session_summary",
                new_callable=AsyncMock,
                return_value=MagicMock(skipped=True, summary=""),
            ),
            patch(
                "app.services.memory.summary_generator._store_summary_on_session",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            result = await _ensure_session_summary("sess-1", content)

        assert result is True
        mock_store.assert_awaited_once()
        call_kwargs = mock_store.call_args[1]
        assert call_kwargs["session_id"] == "sess-1"
        assert "Routine check completed" in call_kwargs["summary_oneliner"]

    @pytest.mark.asyncio
    async def test_empty_content_stores_fallback_summary(self):
        """Empty content stores fallback summary and returns True."""
        mock_db = AsyncMock()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.api.complete.citation_tracker.track_inline_summaries",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.services.memory.summary_generator.generate_session_summary",
                new_callable=AsyncMock,
                return_value=MagicMock(skipped=True, summary=""),
            ),
            patch(
                "app.services.memory.summary_generator._store_summary_on_session",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            result = await _ensure_session_summary("sess-1", "")

        assert result is True
        mock_store.assert_awaited_once()
        call_kwargs = mock_store.call_args[1]
        assert call_kwargs["session_id"] == "sess-1"
        assert call_kwargs["summary_oneliner"] == "Heartbeat completed (no output)"

    @pytest.mark.asyncio
    async def test_empty_content_uses_generated_session_summary_when_available(self):
        """Empty content should use transcript-based summary before generic fallback."""
        mock_db = AsyncMock()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.api.complete.citation_tracker.track_inline_summaries",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.services.memory.summary_generator.generate_session_summary",
                new_callable=AsyncMock,
                return_value=MagicMock(skipped=False, summary="Investigated dirty checkout and found coherent in-progress frontend fixes."),
            ) as mock_generate,
            patch(
                "app.services.memory.summary_generator._store_summary_on_session",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            result = await _ensure_session_summary("sess-1", "")

        assert result is True
        mock_generate.assert_awaited_once_with("sess-1")
        mock_store.assert_not_awaited()


class TestPostprocessHeartbeat:
    """Integration tests for postprocess_heartbeat."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """Full postprocess pipeline runs all steps."""
        result = _make_result()

        with (
            patch(
                "app.workflows._heartbeat_postprocess._ensure_session_summary",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows._heartbeat_postprocess._retry_failed_mcp_tools",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.workflows._heartbeat_redis.record_heartbeat_metrics",
                new_callable=AsyncMock,
            ) as mock_metrics,
            patch(
                "app.workflows._heartbeat_postprocess._get_cleanup_status_summary",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_postprocess._get_workstream_inventory",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_postprocess.review_persona_completion",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    used=True,
                    decision="complete",
                    reason="No unfinished residue remains.",
                    session_id="review-sess-1",
                    reviewer_agent_slug="supervisor",
                    reviewer_model_id="codex/gpt-5.4",
                ),
            ),
            patch(
                "app.workflows._heartbeat_postprocess._warm_recall_cache",
                new_callable=AsyncMock,
            ) as mock_warm_recall,
        ):
            hb_result = await postprocess_heartbeat(result, 60)

        assert hb_result.status == "success"
        assert hb_result.format_compliant is True
        assert hb_result.summary_stored is True
        assert hb_result.turns == 3
        assert hb_result.tool_calls == 5
        assert hb_result.interval_minutes == 60
        assert hb_result.followup_dispatched is False
        assert hb_result.followup_reason is None
        assert hb_result.completion_review_used is True
        assert hb_result.completion_review_decision == "complete"
        mock_metrics.assert_awaited_once()
        mock_warm_recall.assert_awaited_once_with(None)

    @pytest.mark.asyncio
    async def test_error_result_propagates(self):
        """Error from completion propagates through postprocessor."""
        result = _make_result(
            content="", error="Provider timeout", status="error"
        )

        with (
            patch(
                "app.workflows._heartbeat_postprocess._ensure_session_summary",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workflows._heartbeat_postprocess._retry_failed_mcp_tools",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.workflows._heartbeat_redis.record_heartbeat_metrics",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workflows._heartbeat_postprocess._get_cleanup_status_summary",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_postprocess._get_workstream_inventory",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_postprocess.review_persona_completion",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    used=True,
                    decision="complete",
                    reason="No unfinished residue remains.",
                    session_id="review-sess-2",
                    reviewer_agent_slug="supervisor",
                    reviewer_model_id="codex/gpt-5.4",
                ),
            ),
            patch(
                "app.workflows._heartbeat_postprocess._warm_recall_cache",
                new_callable=AsyncMock,
            ),
        ):
            hb_result = await postprocess_heartbeat(result, 60)

        assert hb_result.error == "Provider timeout"

    @pytest.mark.asyncio
    async def test_pipeline_dispatches_followup_for_obvious_unresolved_cleanup(self) -> None:
        result = _make_result(content="HEARTBEAT_OK — Routine sweep complete.")

        with (
            patch(
                "app.workflows._heartbeat_postprocess._ensure_session_summary",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows._heartbeat_postprocess._retry_failed_mcp_tools",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.workflows._heartbeat_redis.record_heartbeat_metrics",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workflows._heartbeat_postprocess._get_cleanup_status_summary",
                new_callable=AsyncMock,
                return_value="\n<cleanup_status>\nACTIONABLE-CLEANUP[1]\n- agent-hub | finalize | task-123\n</cleanup_status>",
            ),
            patch(
                "app.workflows._heartbeat_postprocess._get_workstream_inventory",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_postprocess._dispatch_followup_wake",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_dispatch,
            patch(
                "app.workflows._heartbeat_postprocess._warm_recall_cache",
                new_callable=AsyncMock,
            ),
        ):
            hb_result = await postprocess_heartbeat(result, 60)

        assert hb_result.followup_dispatched is True
        assert hb_result.followup_reason == "cleanup_actionable"
        assert hb_result.completion_review_used is False
        mock_dispatch.assert_awaited_once_with(
            "cleanup_actionable",
            None,
            note=None,
            parent_session_id="sess-test-123",
        )

    @pytest.mark.asyncio
    async def test_completion_review_dispatches_followup_when_supervisor_requests_continue(self) -> None:
        result = _make_result(content="HEARTBEAT_OK — Routine sweep complete.")

        with (
            patch(
                "app.workflows._heartbeat_postprocess._ensure_session_summary",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows._heartbeat_postprocess._retry_failed_mcp_tools",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.workflows._heartbeat_redis.record_heartbeat_metrics",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workflows._heartbeat_postprocess._get_cleanup_status_summary",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_postprocess._get_workstream_inventory",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_postprocess.review_persona_completion",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    used=True,
                    decision="continue",
                    reason="A quiet active lane still needs one more inspect/poll step.",
                    session_id="review-sess-3",
                    reviewer_agent_slug="supervisor",
                    reviewer_model_id="claude-opus-4-6",
                ),
            ),
            patch(
                "app.workflows._heartbeat_postprocess._dispatch_followup_wake",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_dispatch,
            patch(
                "app.workflows._heartbeat_postprocess._warm_recall_cache",
                new_callable=AsyncMock,
            ),
        ):
            hb_result = await postprocess_heartbeat(result, 60)

        assert hb_result.followup_dispatched is True
        assert hb_result.followup_reason == "completion_review_continue"
        assert hb_result.completion_review_used is True
        assert hb_result.completion_review_decision == "continue"
        assert hb_result.completion_review_reason == "A quiet active lane still needs one more inspect/poll step."
        assert hb_result.completion_review_model_id == "claude-opus-4-6"
        mock_dispatch.assert_awaited_once_with(
            "completion_review_continue",
            None,
            note="A quiet active lane still needs one more inspect/poll step.",
            parent_session_id="sess-test-123",
        )

    @pytest.mark.asyncio
    async def test_pipeline_logs_system_performance_signal_for_review_followup(self) -> None:
        result = _make_result(content="HEARTBEAT_OK — Routine sweep complete.")

        with (
            patch(
                "app.workflows._heartbeat_postprocess._ensure_session_summary",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows._heartbeat_postprocess._retry_failed_mcp_tools",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.workflows._heartbeat_redis.record_heartbeat_metrics",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workflows._heartbeat_postprocess._get_cleanup_status_summary",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_postprocess._get_workstream_inventory",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_postprocess.review_persona_completion",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    used=True,
                    decision="continue",
                    reason="A quiet active lane still needs one more inspect/poll step.",
                    session_id="review-sess-3",
                    reviewer_agent_slug="supervisor",
                    reviewer_model_id="claude-opus-4-6",
                ),
            ),
            patch(
                "app.workflows._heartbeat_postprocess._dispatch_followup_wake",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows._heartbeat_postprocess.log_agent_performance",
                new_callable=AsyncMock,
            ) as mock_log,
            patch(
                "app.workflows._heartbeat_postprocess._warm_recall_cache",
                new_callable=AsyncMock,
            ),
        ):
            await postprocess_heartbeat(result, 60)

        mock_log.assert_awaited_once()
        await_args = mock_log.await_args
        assert await_args is not None
        kwargs = await_args.kwargs
        assert kwargs["agent_slug"] == "persona"
        assert kwargs["feedback_type"] == "friction"
        assert kwargs["logged_by"] == "system"
        assert kwargs["task_type"] == "heartbeat"
        assert "completion review requested continue" in kwargs["content"]


class TestMaybeReviewCompletion:
    @pytest.mark.asyncio
    async def test_skips_model_review_when_deterministic_residue_exists(self) -> None:
        with (
            patch(
                "app.workflows._heartbeat_postprocess._get_cleanup_status_summary",
                new_callable=AsyncMock,
                return_value="ACTIONABLE-CLEANUP[1]",
            ),
            patch(
                "app.workflows._heartbeat_postprocess._get_workstream_inventory",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_postprocess.review_persona_completion",
                new_callable=AsyncMock,
            ) as mock_review,
        ):
            outcome = await _maybe_review_completion(
                content="HEARTBEAT_OK — Routine sweep complete.",
                session_id="sess-test-123",
                target_project_id=None,
                cleanup_status="ACTIONABLE-CLEANUP[1]",
                workstream_inventory="",
            )

        assert outcome is None
        mock_review.assert_not_awaited()
