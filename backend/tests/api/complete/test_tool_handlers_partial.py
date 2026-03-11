"""Tests for tool_handlers partial response storage on error paths."""

from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.complete.tool_handler_utils import _ExecutionState, _run_tool_loop
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


@pytest.mark.asyncio
async def test_run_tool_loop_drains_stream_after_terminal_error() -> None:
    """Terminal error events should not abort the provider stream mid-iteration."""
    state = _ExecutionState(agent_slug="persona", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()
    stream_state = {"natural_end": False, "closed_early": False}

    async def fake_event_stream():
        try:
            yield types.SimpleNamespace(type="error", error="claude tool failed"), None
            yield types.SimpleNamespace(type="result", result="ignored"), None
            stream_state["natural_end"] = True
        finally:
            if not stream_state["natural_end"]:
                stream_state["closed_early"] = True

    with patch(
        "app.api.complete.tool_handler_utils.build_event_stream",
        return_value=fake_event_stream(),
    ):
        result = await _run_tool_loop(
            adapter=MagicMock(),
            state=state,
            provider="claude",
            model="claude-sonnet-4-6",
            tools=[],
            tool_catalog=None,
            working_dir=None,
            permission_config=None,
            session_id="session-123",
            loaded_memory_uuids=[],
            db=db,
            tracker=tracker,
            max_turns=1,
            project_id="persona-sandbox",
        )

    assert result is not None
    assert result.status == "error"
    assert result.error == "claude tool failed"
    assert stream_state["natural_end"] is True
    assert stream_state["closed_early"] is False
