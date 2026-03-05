"""Tests for heartbeat post-processing — summaries and format validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows._heartbeat_postprocess import (
    _ensure_session_summary,
    _extract_synthetic_summary,
    _validate_heartbeat_format,
    postprocess_heartbeat,
)


def _make_result(**overrides):
    """Create a mock CompletionInternalResult."""
    defaults = {
        "content": "HEARTBEAT_OK — All systems normal.",
        "session_id": "sess-test-123",
        "turns": 3,
        "tool_calls_count": 5,
        "status": "success",
        "error": None,
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


class TestValidateHeartbeatFormat:
    """Tests for _validate_heartbeat_format."""

    def test_heartbeat_ok_format(self):
        status, compliant = _validate_heartbeat_format("HEARTBEAT_OK — Everything fine.")
        assert status == "success"
        assert compliant is True

    def test_heartbeat_action_format(self):
        status, compliant = _validate_heartbeat_format("HEARTBEAT_ACTION — Deployed fix.")
        assert status == "action"
        assert compliant is True

    def test_noncompliant_format(self):
        status, compliant = _validate_heartbeat_format("I did some stuff today.")
        assert status == "success"
        assert compliant is False

    def test_empty_content(self):
        status, compliant = _validate_heartbeat_format("")
        assert status == "success"
        assert compliant is False

    def test_none_content(self):
        status, compliant = _validate_heartbeat_format(None)
        assert status == "success"
        assert compliant is False


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
                "app.workflows._heartbeat_redis.record_heartbeat_metrics",
                new_callable=AsyncMock,
            ) as mock_metrics,
        ):
            hb_result = await postprocess_heartbeat(result, 60)

        assert hb_result.status == "success"
        assert hb_result.format_compliant is True
        assert hb_result.summary_stored is True
        assert hb_result.auto_journaled is False
        assert hb_result.turns == 3
        assert hb_result.tool_calls == 5
        assert hb_result.interval_minutes == 60
        mock_metrics.assert_awaited_once()

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
                "app.workflows._heartbeat_redis.record_heartbeat_metrics",
                new_callable=AsyncMock,
            ),
        ):
            hb_result = await postprocess_heartbeat(result, 60)

        assert hb_result.error == "Provider timeout"
        assert hb_result.auto_journaled is False


