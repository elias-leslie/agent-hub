"""Tests for streaming functionality."""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from agent_hub import AsyncAgentHubClient, StreamChunk, AgentHubError


class TestStreamSSE:
    """Tests for SSE streaming."""

    @pytest.mark.asyncio
    async def test_stream_sse_success(self, httpx_mock: HTTPXMock) -> None:
        """Test successful SSE streaming."""
        # SSE response body
        sse_body = (
            'data: {"id":"1","choices":[{"delta":{"role":"assistant"}}]}\n\n'
            'data: {"id":"1","choices":[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"id":"1","choices":[{"delta":{"content":" world"}}]}\n\n'
            'data: {"id":"1","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        )

        httpx_mock.add_response(
            url="http://localhost:8003/api/v1/chat/completions",
            method="POST",
            content=sse_body.encode(),
            headers={"content-type": "text/event-stream"},
        )

        async with AsyncAgentHubClient() as client:
            chunks = []
            async for chunk in client.stream_sse(
                model="claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Hello"}],
            ):
                chunks.append(chunk)

        # Should have: 2 content chunks + 1 done
        assert len(chunks) == 3
        assert chunks[0].type == "content"
        assert chunks[0].content == "Hello"
        assert chunks[1].type == "content"
        assert chunks[1].content == " world"
        assert chunks[2].type == "done"
        assert chunks[2].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_stream_sse_with_message_input(self, httpx_mock: HTTPXMock) -> None:
        """Test SSE streaming with MessageInput objects."""
        from agent_hub import MessageInput

        sse_body = (
            'data: {"id":"1","choices":[{"delta":{"content":"Response"}}]}\n\n'
            'data: [DONE]\n\n'
        )

        httpx_mock.add_response(
            url="http://localhost:8003/api/v1/chat/completions",
            method="POST",
            content=sse_body.encode(),
            headers={"content-type": "text/event-stream"},
        )

        async with AsyncAgentHubClient() as client:
            chunks = []
            async for chunk in client.stream_sse(
                model="claude-sonnet-4-5",
                messages=[MessageInput(role="user", content="Hello")],
            ):
                chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].content == "Response"

    @pytest.mark.asyncio
    async def test_stream_sse_done_marker(self, httpx_mock: HTTPXMock) -> None:
        """Test SSE streaming handles [DONE] marker."""
        sse_body = (
            'data: {"id":"1","choices":[{"delta":{"content":"Text"}}]}\n\n'
            'data: [DONE]\n\n'
        )

        httpx_mock.add_response(
            url="http://localhost:8003/api/v1/chat/completions",
            method="POST",
            content=sse_body.encode(),
            headers={"content-type": "text/event-stream"},
        )

        async with AsyncAgentHubClient() as client:
            chunks = []
            async for chunk in client.stream_sse(
                model="claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Hello"}],
            ):
                chunks.append(chunk)

        # Last chunk should be done with finish_reason from [DONE]
        assert chunks[-1].type == "done"
        assert chunks[-1].finish_reason == "stop"


class TestStreamWebSocket:
    """Tests for WebSocket streaming."""

    @pytest.mark.asyncio
    async def test_stream_websocket_success(self) -> None:
        """Test successful WebSocket streaming."""
        ws_messages = [
            '{"type": "content", "content": "Hello"}',
            '{"type": "content", "content": " world"}',
            '{"type": "done", "input_tokens": 10, "output_tokens": 5, "finish_reason": "end_turn"}',
        ]

        mock_websocket = AsyncMock()
        mock_websocket.send = AsyncMock()

        async def mock_aiter():
            for msg in ws_messages:
                yield msg

        mock_websocket.__aiter__ = lambda self: mock_aiter()

        with patch("websockets.connect") as mock_connect:
            mock_connect.return_value.__aenter__.return_value = mock_websocket
            mock_connect.return_value.__aexit__.return_value = None

            async with AsyncAgentHubClient() as client:
                chunks = []
                async for chunk in client.stream(
                    model="claude-sonnet-4-5",
                    messages=[{"role": "user", "content": "Hello"}],
                ):
                    chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0].type == "content"
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " world"
        assert chunks[2].type == "done"
        assert chunks[2].input_tokens == 10
        assert chunks[2].output_tokens == 5

    @pytest.mark.asyncio
    async def test_stream_websocket_cancelled(self) -> None:
        """Test WebSocket stream cancellation handling."""
        ws_messages = [
            '{"type": "content", "content": "Starting..."}',
            '{"type": "cancelled", "input_tokens": 20, "output_tokens": 10, "finish_reason": "cancelled"}',
        ]

        mock_websocket = AsyncMock()
        mock_websocket.send = AsyncMock()

        async def mock_aiter():
            for msg in ws_messages:
                yield msg

        mock_websocket.__aiter__ = lambda self: mock_aiter()

        with patch("websockets.connect") as mock_connect:
            mock_connect.return_value.__aenter__.return_value = mock_websocket
            mock_connect.return_value.__aexit__.return_value = None

            async with AsyncAgentHubClient() as client:
                chunks = []
                async for chunk in client.stream(
                    model="claude-sonnet-4-5",
                    messages=[{"role": "user", "content": "Hello"}],
                ):
                    chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[1].type == "cancelled"
        assert chunks[1].finish_reason == "cancelled"

    @pytest.mark.asyncio
    async def test_stream_websocket_error_response(self) -> None:
        """Test WebSocket stream error response handling."""
        ws_messages = [
            '{"type": "error", "error": "Model not available"}',
        ]

        mock_websocket = AsyncMock()
        mock_websocket.send = AsyncMock()

        async def mock_aiter():
            for msg in ws_messages:
                yield msg

        mock_websocket.__aiter__ = lambda self: mock_aiter()

        with patch("websockets.connect") as mock_connect:
            mock_connect.return_value.__aenter__.return_value = mock_websocket
            mock_connect.return_value.__aexit__.return_value = None

            async with AsyncAgentHubClient() as client:
                chunks = []
                async for chunk in client.stream(
                    model="invalid-model",
                    messages=[{"role": "user", "content": "Hello"}],
                ):
                    chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].type == "error"
        assert chunks[0].error == "Model not available"

    @pytest.mark.asyncio
    async def test_stream_websocket_sends_session_id(self) -> None:
        """Test WebSocket stream includes session_id in request."""
        ws_messages = ['{"type": "done", "finish_reason": "end_turn"}']

        mock_websocket = AsyncMock()
        sent_messages = []

        async def capture_send(msg):
            sent_messages.append(msg)

        mock_websocket.send = capture_send

        async def mock_aiter():
            for msg in ws_messages:
                yield msg

        mock_websocket.__aiter__ = lambda self: mock_aiter()

        with patch("websockets.connect") as mock_connect:
            mock_connect.return_value.__aenter__.return_value = mock_websocket
            mock_connect.return_value.__aexit__.return_value = None

            async with AsyncAgentHubClient() as client:
                async for _ in client.stream(
                    model="claude-sonnet-4-5",
                    messages=[{"role": "user", "content": "Hello"}],
                    session_id="test-session-123",
                ):
                    pass

        assert len(sent_messages) == 1
        request = json.loads(sent_messages[0])
        assert request["session_id"] == "test-session-123"

    @pytest.mark.asyncio
    async def test_stream_websocket_reconnection(self) -> None:
        """Test WebSocket reconnection on disconnect."""
        import websockets

        call_count = 0
        ws_messages = ['{"type": "done", "finish_reason": "end_turn"}']

        async def mock_aiter():
            for msg in ws_messages:
                yield msg

        with patch("websockets.connect") as mock_connect:
            async def create_websocket(*args, **kwargs):
                nonlocal call_count
                call_count += 1

                mock_ws = AsyncMock()
                mock_ws.send = AsyncMock()

                if call_count < 2:
                    # First attempt fails
                    async def failing_aiter():
                        raise websockets.exceptions.ConnectionClosed(None, None)
                        yield  # Make it a generator

                    mock_ws.__aiter__ = lambda self: failing_aiter()
                else:
                    # Second attempt succeeds
                    mock_ws.__aiter__ = lambda self: mock_aiter()

                return mock_ws

            mock_context = AsyncMock()
            mock_context.__aenter__ = create_websocket
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_connect.return_value = mock_context

            async with AsyncAgentHubClient() as client:
                chunks = []
                async for chunk in client.stream(
                    model="claude-sonnet-4-5",
                    messages=[{"role": "user", "content": "Hello"}],
                    max_retries=3,
                    retry_delay=0.01,  # Fast retry for tests
                ):
                    chunks.append(chunk)

        # Should have reconnected and succeeded
        assert call_count == 2
        assert len(chunks) == 1
        assert chunks[0].type == "done"


class TestStreamChunkModel:
    """Tests for StreamChunk model."""

    def test_stream_chunk_content(self) -> None:
        """Test content chunk creation."""
        chunk = StreamChunk(type="content", content="Hello world")
        assert chunk.type == "content"
        assert chunk.content == "Hello world"
        assert chunk.error is None

    def test_stream_chunk_done(self) -> None:
        """Test done chunk with token counts."""
        chunk = StreamChunk(
            type="done",
            input_tokens=100,
            output_tokens=50,
            finish_reason="end_turn",
        )
        assert chunk.type == "done"
        assert chunk.input_tokens == 100
        assert chunk.output_tokens == 50
        assert chunk.finish_reason == "end_turn"

    def test_stream_chunk_error(self) -> None:
        """Test error chunk."""
        chunk = StreamChunk(type="error", error="Connection failed")
        assert chunk.type == "error"
        assert chunk.error == "Connection failed"

    def test_stream_chunk_cancelled(self) -> None:
        """Test cancelled chunk."""
        chunk = StreamChunk(
            type="cancelled",
            input_tokens=50,
            output_tokens=25,
            finish_reason="cancelled",
        )
        assert chunk.type == "cancelled"
        assert chunk.finish_reason == "cancelled"
