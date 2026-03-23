"""Tests for performance log dedup guard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.models import CLAUDE_SONNET


class TestPerformanceLogDedup:
    """Verify 24h dedup prevents duplicate performance log entries."""

    @pytest.mark.asyncio
    async def test_duplicate_within_24h_is_skipped(self):
        """Second identical log within 24h should be rejected."""
        from app.services.tools._executor_performance import log_agent_performance

        mock_db = AsyncMock()
        # Simulate finding an existing entry
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 42  # existing log id
        mock_db.execute.return_value = mock_result

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.async_session", return_value=mock_session_ctx):
            result = await log_agent_performance(
                agent_slug="coder",
                model_id=CLAUDE_SONNET,
                feedback_type="praise",
                content="Great performance on task X",
            )

        assert "Skipped" in result
        assert "already logged within 24h" in result

    @pytest.mark.asyncio
    async def test_different_content_within_24h_is_not_deduped(self):
        """Different content for the same feedback type should still be recorded."""
        from app.services.tools._executor_performance import log_agent_performance

        mock_db = AsyncMock()
        mock_check_result = MagicMock()
        mock_check_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_check_result
        mock_db.refresh = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.async_session", return_value=mock_session_ctx):
            result = await log_agent_performance(
                agent_slug="coder",
                model_id=CLAUDE_SONNET,
                feedback_type="friction",
                content="Missed rebuild.sh requirement",
            )

        assert "Performance logged" in result
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_entry_after_24h_is_allowed(self):
        """Entry should be created if no duplicate exists within 24h."""
        from app.services.tools._executor_performance import log_agent_performance

        mock_log = MagicMock()
        mock_log.id = 99

        mock_db = AsyncMock()
        # No existing entry found
        mock_check_result = MagicMock()
        mock_check_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_check_result
        mock_db.refresh = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.async_session", return_value=mock_session_ctx):
            result = await log_agent_performance(
                agent_slug="coder",
                model_id=CLAUDE_SONNET,
                feedback_type="praise",
                content="Great performance on task Y",
            )

        assert "Performance logged" in result
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_feedback_type_is_not_deduped(self):
        """Different feedback_type for same agent+model should NOT be deduped."""
        from app.services.tools._executor_performance import log_agent_performance

        mock_db = AsyncMock()
        # No existing entry with this feedback_type
        mock_check_result = MagicMock()
        mock_check_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_check_result
        mock_db.refresh = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.async_session", return_value=mock_session_ctx):
            result = await log_agent_performance(
                agent_slug="coder",
                model_id=CLAUDE_SONNET,
                feedback_type="friction",
                content="Slow on task Z",
            )

        assert "Performance logged" in result
