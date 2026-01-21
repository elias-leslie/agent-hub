"""Unit tests for /api/complete streaming mode.

These are pure unit tests that don't hit any real services.
"""

import pytest

from app.adapters.base import Message, StreamEvent
from app.api.complete import StreamingChunk, _stream_completion


class TestStreamingChunk:
    """Tests for StreamingChunk model."""

    def test_content_chunk(self):
        chunk = StreamingChunk(type="content", content="Hello")
        assert chunk.type == "content"
        assert chunk.content == "Hello"

    def test_done_chunk(self):
        chunk = StreamingChunk(
            type="done",
            model="claude-sonnet-4-5",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
            session_id="test-session",
        )
        assert chunk.type == "done"
        assert chunk.model == "claude-sonnet-4-5"
        assert chunk.input_tokens == 10

    def test_error_chunk(self):
        chunk = StreamingChunk(type="error", error="Something went wrong")
        assert chunk.type == "error"
        assert chunk.error == "Something went wrong"

    def test_agent_routing_fields(self):
        chunk = StreamingChunk(
            type="done",
            agent_used="coder",
            model_used="claude-haiku-4-5",
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
            yield StreamEvent(type="done", finish_reason="end_turn", input_tokens=5, output_tokens=2)

        with patch("app.api.complete._get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.stream = mock_stream
            mock_get_adapter.return_value = mock_adapter

            messages = [Message(role="user", content="Hi")]
            chunks = []

            async for chunk in _stream_completion(
                messages=messages,
                model="claude-sonnet-4-5",
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
            yield StreamEvent(type="done", finish_reason="end_turn", input_tokens=5, output_tokens=3)

        with patch("app.api.complete._get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.stream = mock_stream
            mock_get_adapter.return_value = mock_adapter

            messages = [Message(role="user", content="Hi")]
            chunks = []

            async for chunk in _stream_completion(
                messages=messages,
                model="claude-sonnet-4-5",
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

        with patch("app.api.complete._get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.stream = mock_stream
            mock_get_adapter.return_value = mock_adapter

            messages = [Message(role="user", content="Hi")]
            chunks = []

            async for chunk in _stream_completion(
                messages=messages,
                model="claude-sonnet-4-5",
                provider="claude",
                max_tokens=100,
                temperature=0.7,
                session_id="test-session",
                agent_used="coder",
                model_used="claude-sonnet-4-5",
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
            assert done_chunk["model"] == "claude-sonnet-4-5"
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

        with patch("app.api.complete._get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.stream = mock_stream
            mock_get_adapter.return_value = mock_adapter

            messages = [Message(role="user", content="Hi")]
            chunks = []

            async for chunk in _stream_completion(
                messages=messages,
                model="claude-sonnet-4-5",
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
