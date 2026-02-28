"""Tests for result_finalizer — session status finalization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFinalizeCompletionResult:
    """Tests for finalize_completion_result session status logic."""

    @pytest.mark.asyncio
    async def test_new_session_marked_completed(self):
        """New sessions are always marked completed."""
        from app.api.complete.result_finalizer import finalize_completion_result

        session = MagicMock()
        session.status = "active"
        db = AsyncMock()

        with (
            patch("app.api.complete.result_finalizer.estimate_cost", return_value=MagicMock(total_cost_usd=0.001)),
            patch("app.api.complete.result_finalizer.log_token_usage", new_callable=AsyncMock),
            patch("app.api.complete.result_finalizer.publish_complete", new_callable=AsyncMock),
        ):
            await finalize_completion_result(
                db=db,
                session=session,
                session_id="sess-1",
                model="claude-haiku",
                total_input_tokens=100,
                total_output_tokens=50,
                is_new_session=True,
            )

        assert session.status == "completed"

    @pytest.mark.asyncio
    async def test_completion_type_session_marked_completed(self):
        """Completion-type sessions are marked completed even when not new."""
        from app.api.complete.result_finalizer import finalize_completion_result

        session = MagicMock()
        session.status = "active"
        session.session_type = "completion"
        db = AsyncMock()

        with (
            patch("app.api.complete.result_finalizer.estimate_cost", return_value=MagicMock(total_cost_usd=0.001)),
            patch("app.api.complete.result_finalizer.log_token_usage", new_callable=AsyncMock),
            patch("app.api.complete.result_finalizer.publish_complete", new_callable=AsyncMock),
        ):
            await finalize_completion_result(
                db=db,
                session=session,
                session_id="sess-2",
                model="claude-haiku",
                total_input_tokens=100,
                total_output_tokens=50,
                is_new_session=False,
            )

        assert session.status == "completed"

    @pytest.mark.asyncio
    async def test_existing_non_completion_session_stays_active(self):
        """Existing non-completion sessions are not automatically completed."""
        from app.api.complete.result_finalizer import finalize_completion_result

        session = MagicMock()
        session.status = "active"
        session.session_type = "chat"
        db = AsyncMock()

        with (
            patch("app.api.complete.result_finalizer.estimate_cost", return_value=MagicMock(total_cost_usd=0.001)),
            patch("app.api.complete.result_finalizer.log_token_usage", new_callable=AsyncMock),
            patch("app.api.complete.result_finalizer.publish_complete", new_callable=AsyncMock),
        ):
            await finalize_completion_result(
                db=db,
                session=session,
                session_id="sess-3",
                model="claude-haiku",
                total_input_tokens=100,
                total_output_tokens=50,
                is_new_session=False,
            )

        assert session.status == "active"
