"""Tests for streaming session context ownership."""

from __future__ import annotations

from app.api.complete.streaming_context import StreamContext


class TestStreamContextRegistry:
    """Streaming cancel ownership should live on the context itself."""

    def test_open_registers_cancel_and_close(self) -> None:
        ctx = StreamContext.open(
            session_id="stream-ctx-test",
            model="claude-sonnet-4-5",
            provider="claude",
            agent_used=None,
            model_used=None,
            fallback_used=False,
            user_messages=None,
            stream_start=0.0,
            is_new_session=False,
            is_one_shot=False,
            project_id=None,
        )

        assert ctx.cancel_event is not None
        assert ctx.cancel_event.is_set() is False
        assert StreamContext.cancel("stream-ctx-test") is True
        assert ctx.cancel_event.is_set() is True

        ctx.close()

        assert StreamContext.cancel("stream-ctx-test") is False

    def test_close_is_idempotent(self) -> None:
        ctx = StreamContext.open(
            session_id="stream-ctx-idempotent",
            model="claude-sonnet-4-5",
            provider="claude",
            agent_used=None,
            model_used=None,
            fallback_used=False,
            user_messages=None,
            stream_start=0.0,
            is_new_session=False,
            is_one_shot=False,
            project_id=None,
        )

        ctx.close()
        ctx.close()

        assert StreamContext.cancel("stream-ctx-idempotent") is False
