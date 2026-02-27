"""Unit tests for /api/complete streaming mode.

These are pure unit tests that don't hit any real services.
"""

import asyncio

import pytest

from app.adapters.base import Message, StreamEvent
from app.api.complete import StreamingChunk, stream_completion
from app.api.complete.streaming import _with_heartbeat
from app.constants.models import CLAUDE_HAIKU, CLAUDE_SONNET


class TestStreamingChunk:
    """Tests for StreamingChunk model."""

    def test_content_chunk(self):
        chunk = StreamingChunk(type="content", content="Hello")
        assert chunk.type == "content"
        assert chunk.content == "Hello"

    def test_done_chunk(self):
        chunk = StreamingChunk(
            type="done",
            model=CLAUDE_SONNET,
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
            session_id="test-session",
        )
        assert chunk.type == "done"
        assert chunk.model == CLAUDE_SONNET
        assert chunk.input_tokens == 10

    def test_error_chunk(self):
        chunk = StreamingChunk(type="error", error="Something went wrong")
        assert chunk.type == "error"
        assert chunk.error == "Something went wrong"

    def test_agent_routing_fields(self):
        chunk = StreamingChunk(
            type="done",
            agent_used="coder",
            model_used=CLAUDE_HAIKU,
            fallback_used=True,
        )
        assert chunk.agent_used == "coder"
        assert chunk.model_used == "claude-haiku-4-5"
        assert chunk.fallback_used is True


class TestStreamCompletionGenerator:
    """Tests for _stream_completion generator."""

    @pytest.mark.asyncio
    async def test_yields_sse_format(self):
        """Test that generator yields proper SSE format."""
        from unittest.mock import AsyncMock, patch

        # Create mock stream events
        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="content", content="Hello")
            yield StreamEvent(
                type="done", finish_reason="end_turn", input_tokens=5, output_tokens=2
            )

        with patch("app.api.complete.streaming.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.stream = mock_stream
            mock_get_adapter.return_value = mock_adapter

            messages = [Message(role="user", content="Hi")]
            chunks = []

            async for chunk in stream_completion(
                messages=messages,
                model=CLAUDE_SONNET,
                provider="claude",
                max_tokens=100,
                temperature=0.7,
                session_id="test-session",
            ):
                chunks.append(chunk)

            # All chunks should be SSE format
            for chunk in chunks:
                assert chunk.startswith("data: "), f"Not SSE format: {chunk}"

            # Should end with [DONE]
            assert chunks[-1] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_content_events(self):
        """Test content events are properly formatted."""
        from unittest.mock import AsyncMock, patch

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="content", content="Hello")
            yield StreamEvent(type="content", content=" world")
            yield StreamEvent(
                type="done", finish_reason="end_turn", input_tokens=5, output_tokens=3
            )

        with patch("app.api.complete.streaming.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.stream = mock_stream
            mock_get_adapter.return_value = mock_adapter

            messages = [Message(role="user", content="Hi")]
            chunks = []

            async for chunk in stream_completion(
                messages=messages,
                model=CLAUDE_SONNET,
                provider="claude",
                max_tokens=100,
                temperature=0.7,
                session_id="test-session",
            ):
                chunks.append(chunk)

            # Parse content chunks
            content_chunks = [c for c in chunks if '"type":"content"' in c]
            assert len(content_chunks) == 2

    @pytest.mark.asyncio
    async def test_done_event_includes_metadata(self):
        """Test done event includes all metadata."""
        import json
        from unittest.mock import AsyncMock, patch

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(
                type="done",
                finish_reason="end_turn",
                input_tokens=10,
                output_tokens=5,
            )

        with patch("app.api.complete.streaming.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.stream = mock_stream
            mock_get_adapter.return_value = mock_adapter

            messages = [Message(role="user", content="Hi")]
            chunks = []

            async for chunk in stream_completion(
                messages=messages,
                model=CLAUDE_SONNET,
                provider="claude",
                max_tokens=100,
                temperature=0.7,
                session_id="test-session",
                agent_used="coder",
                model_used=CLAUDE_SONNET,
                fallback_used=False,
            ):
                chunks.append(chunk)

            # Find done chunk
            done_chunk = None
            for c in chunks:
                if '"type":"done"' in c:
                    data = c.replace("data: ", "").strip()
                    done_chunk = json.loads(data)
                    break

            assert done_chunk is not None
            assert done_chunk["model"] == CLAUDE_SONNET
            assert done_chunk["provider"] == "claude"
            assert done_chunk["session_id"] == "test-session"
            assert done_chunk["agent_used"] == "coder"
            assert done_chunk["input_tokens"] == 10
            assert done_chunk["output_tokens"] == 5

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Test error events are properly formatted."""
        from unittest.mock import AsyncMock, patch

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="error", error="API error occurred")

        with patch("app.api.complete.streaming.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.stream = mock_stream
            mock_get_adapter.return_value = mock_adapter

            messages = [Message(role="user", content="Hi")]
            chunks = []

            async for chunk in stream_completion(
                messages=messages,
                model=CLAUDE_SONNET,
                provider="claude",
                max_tokens=100,
                temperature=0.7,
                session_id="test-session",
            ):
                chunks.append(chunk)

            # Should have error chunk
            error_chunks = [c for c in chunks if '"type":"error"' in c]
            assert len(error_chunks) == 1
            assert "API error occurred" in error_chunks[0]


class TestWithHeartbeat:
    """Tests for _with_heartbeat SSE keepalive wrapper."""

    @pytest.mark.asyncio
    async def test_heartbeat_emitted_after_slow_chunk(self):
        """Heartbeat emitted when inner generator was slow (catch-up on next yield)."""

        async def slow_gen():
            await asyncio.sleep(0.3)  # longer than heartbeat interval
            yield "data: slow-chunk\n\n"

        results = []
        async for item in _with_heartbeat(slow_gen(), interval=0.1):
            results.append(item)

        heartbeats = [r for r in results if r == ": heartbeat\n\n"]
        data_chunks = [r for r in results if r.startswith("data:")]
        assert len(heartbeats) >= 1, "Should emit at least one heartbeat"
        assert len(data_chunks) == 1, "Slow chunk must still arrive"
        assert data_chunks[0] == "data: slow-chunk\n\n"

    @pytest.mark.asyncio
    async def test_fast_chunks_no_heartbeat(self):
        """No heartbeat when chunks arrive faster than interval."""

        async def fast_gen():
            yield "data: a\n\n"
            yield "data: b\n\n"

        results = []
        async for item in _with_heartbeat(fast_gen(), interval=5.0):
            results.append(item)

        assert results == ["data: a\n\n", "data: b\n\n"]

    @pytest.mark.asyncio
    async def test_multiple_slow_chunks_all_arrive(self):
        """Multiple slow chunks all arrive with heartbeats interspersed."""

        async def multi_slow_gen():
            await asyncio.sleep(0.25)
            yield "data: first\n\n"
            await asyncio.sleep(0.25)
            yield "data: second\n\n"

        results = []
        async for item in _with_heartbeat(multi_slow_gen(), interval=0.1):
            results.append(item)

        data_chunks = [r for r in results if r.startswith("data:")]
        assert data_chunks == ["data: first\n\n", "data: second\n\n"]

    @pytest.mark.asyncio
    async def test_heartbeat_does_not_cancel_inner_generator(self):
        """Direct iteration never cancels the inner generator."""
        cancel_detected = False

        async def cancellation_sensitive_gen():
            nonlocal cancel_detected
            try:
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                cancel_detected = True
                raise
            yield "data: survived\n\n"

        results = []
        async for item in _with_heartbeat(cancellation_sensitive_gen(), interval=0.1):
            results.append(item)

        assert not cancel_detected, "Inner generator must NOT receive CancelledError"
        data_chunks = [r for r in results if r.startswith("data:")]
        assert len(data_chunks) == 1, "Data chunk must arrive after heartbeats"

    @pytest.mark.asyncio
    async def test_no_separate_tasks_created(self):
        """Regression: _with_heartbeat must NOT create separate asyncio Tasks.

        The Claude SDK uses anyio cancel scopes bound to the current Task.
        Creating separate Tasks (ensure_future, create_task, Queue+drain)
        causes RuntimeError on cleanup and 100% CPU spin.
        """
        observed_tasks: list[int] = []
        caller_task = id(asyncio.current_task())

        async def task_tracking_gen():
            for i in range(4):
                observed_tasks.append(id(asyncio.current_task()))
                yield f"data: chunk-{i}\n\n"

        results = []
        async for item in _with_heartbeat(task_tracking_gen(), interval=5.0):
            results.append(item)

        assert len(observed_tasks) == 4
        # All iterations must run in the CALLER's task — no separate tasks
        assert all(t == caller_task for t in observed_tasks), (
            "Generator must run in caller's task, not a separate task"
        )
