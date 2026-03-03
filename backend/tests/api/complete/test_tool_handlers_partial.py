"""Tests for tool_handlers partial response storage on error paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.complete.tool_handler_utils import _ExecutionState
from app.api.complete.tool_handlers import _store_partial_response


def _mock_session() -> MagicMock:
    """Create a mock DBSession with a mutable status attribute."""
    session = MagicMock()
    session.status = "active"
    return session


class TestStorePartialResponse:
    """Verify _store_partial_response stores accumulated content on error."""

    @pytest.mark.asyncio
    async def test_stores_accumulated_content(self):
        """Partial content should be stored even when tool loop fails."""
        state = _ExecutionState(
            agent_slug="persona",
            messages_for_adapter=[],
            content_parts=["Hello, ", "I found an issue with..."],
            thinking_parts=["Let me check the logs"],
        )
        mock_db = AsyncMock()
        session = _mock_session()

        with patch(
            "app.api.complete.tool_handlers.store_assistant_response",
            new_callable=AsyncMock,
        ) as mock_store:
            await _store_partial_response(mock_db, "session-123", session, state, "claude-sonnet-4-5")

            # Rollback called before storage to clear dirty transaction state
            mock_db.rollback.assert_called_once()
            mock_store.assert_called_once()
            call_kwargs = mock_store.call_args
            # Content should be joined
            assert call_kwargs[0][2] == "Hello, I found an issue with..."
            # Model passed through
            assert call_kwargs[0][3] == "claude-sonnet-4-5"
            # Session marked as completed
            assert session.status == "completed"
            # db.commit() called after storage
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_stores_fallback_content_on_early_error(self):
        """With no accumulated content, a fallback message should be stored."""
        state = _ExecutionState(
            agent_slug="persona",
            messages_for_adapter=[],
            content_parts=[],
            thinking_parts=[],
        )
        mock_db = AsyncMock()
        session = _mock_session()

        with patch(
            "app.api.complete.tool_handlers.store_assistant_response",
            new_callable=AsyncMock,
        ) as mock_store:
            await _store_partial_response(mock_db, "session-456", session, state, "claude-sonnet-4-5")

            mock_db.rollback.assert_called_once()
            mock_store.assert_called_once()
            assert mock_store.call_args[0][2] == "Session interrupted before response"
            assert session.status == "completed"

    @pytest.mark.asyncio
    async def test_suppresses_storage_errors(self):
        """Storage failure should not raise — it's a best-effort operation."""
        state = _ExecutionState(
            agent_slug="persona",
            messages_for_adapter=[],
            content_parts=["partial"],
        )
        mock_db = AsyncMock()
        session = _mock_session()

        with patch(
            "app.api.complete.tool_handlers.store_assistant_response",
            new_callable=AsyncMock,
            side_effect=Exception("DB connection lost"),
        ):
            # Should not raise
            await _store_partial_response(mock_db, "session-789", session, state, "claude-sonnet-4-5")
