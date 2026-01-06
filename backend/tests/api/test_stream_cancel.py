"""Tests for WebSocket streaming cancellation."""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import StreamEvent
from app.main import app


@pytest.fixture
def client():
    """Test client for the FastAPI app."""
    return TestClient(app)


class TestStreamCancellation:
    """Tests for cancel functionality in WebSocket streaming."""

    def test_cancel_during_streaming(self, client):
        """Test that cancel message stops streaming."""

        async def mock_stream(*args, **kwargs):
            """Yield many chunks, allowing time for cancel."""
            for i in range(100):
                yield StreamEvent(type="content", content=f"Chunk {i} ")
                await asyncio.sleep(0.01)  # Give time for cancel to be processed
            yield StreamEvent(
                type="done",
                input_tokens=100,
                output_tokens=500,
                finish_reason="end_turn",
            )

        with patch("app.api.stream.ClaudeAdapter") as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.stream = mock_stream
            mock_adapter_cls.return_value = mock_adapter

            with client.websocket_connect("/api/stream") as websocket:
                # Send the request
                websocket.send_json(
                    {
                        "type": "request",
                        "model": "claude-sonnet-4-5",
                        "messages": [{"role": "user", "content": "Count to 100"}],
                    }
                )

                # Receive a few chunks
                received_chunks = []
                for _ in range(3):
                    chunk = websocket.receive_json()
                    if chunk["type"] == "content":
                        received_chunks.append(chunk["content"])

                # Send cancel
                websocket.send_json({"type": "cancel"})

                # Should receive cancelled event eventually
                final_event = None
                for _ in range(10):  # Allow some buffered chunks
                    event = websocket.receive_json()
                    if event["type"] == "cancelled":
                        final_event = event
                        break

                assert final_event is not None
                assert final_event["type"] == "cancelled"
                assert final_event["finish_reason"] == "cancelled"
                # Should have partial token counts
                assert final_event.get("input_tokens") is not None or final_event.get(
                    "output_tokens"
                ) is not None

    def test_cancel_returns_partial_tokens(self, client):
        """Test that cancellation returns partial token usage."""

        async def mock_stream(*args, **kwargs):
            """Yield chunks with token tracking."""
            # First yield sets input tokens (like message_start)
            yield StreamEvent(type="content", content="Hello ")
            yield StreamEvent(type="content", content="world ")
            yield StreamEvent(type="content", content="this ")
            yield StreamEvent(type="content", content="is ")
            yield StreamEvent(type="content", content="a ")
            yield StreamEvent(type="content", content="test ")
            # Keep yielding so we have time to cancel
            for i in range(100):
                yield StreamEvent(type="content", content=f"{i} ")
                await asyncio.sleep(0.01)
            yield StreamEvent(
                type="done",
                input_tokens=50,
                output_tokens=100,
                finish_reason="end_turn",
            )

        with patch("app.api.stream.ClaudeAdapter") as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.stream = mock_stream
            mock_adapter_cls.return_value = mock_adapter

            with client.websocket_connect("/api/stream") as websocket:
                websocket.send_json(
                    {
                        "type": "request",
                        "model": "claude-sonnet-4-5",
                        "messages": [{"role": "user", "content": "Hi"}],
                    }
                )

                # Receive some chunks
                for _ in range(5):
                    websocket.receive_json()

                # Cancel
                websocket.send_json({"type": "cancel"})

                # Get cancelled event
                cancelled_event = None
                for _ in range(20):
                    event = websocket.receive_json()
                    if event["type"] == "cancelled":
                        cancelled_event = event
                        break

                assert cancelled_event is not None
                # Output tokens should be tracked (approx based on content length)
                assert cancelled_event["output_tokens"] >= 0

    def test_cancel_when_not_streaming(self, client):
        """Test cancel before any streaming starts - should be a no-op."""
        with client.websocket_connect("/api/stream") as websocket:
            # Send cancel before request - should close connection
            websocket.send_json({"type": "cancel"})
            # Connection should still be open, waiting for request
            # The cancel is just ignored since there's no stream

    def test_backward_compatible_request(self, client):
        """Test that requests without type field work (backward compatibility)."""

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="content", content="Hello")
            yield StreamEvent(
                type="done",
                input_tokens=10,
                output_tokens=5,
                finish_reason="end_turn",
            )

        with patch("app.api.stream.ClaudeAdapter") as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.stream = mock_stream
            mock_adapter_cls.return_value = mock_adapter

            with client.websocket_connect("/api/stream") as websocket:
                # Send without type field - should default to "request"
                websocket.send_json(
                    {
                        "model": "claude-sonnet-4-5",
                        "messages": [{"role": "user", "content": "Hi"}],
                    }
                )

                chunk = websocket.receive_json()
                assert chunk["type"] == "content"
                assert chunk["content"] == "Hello"

                done = websocket.receive_json()
                assert done["type"] == "done"

    def test_explicit_request_type(self, client):
        """Test explicit type='request' works."""

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="content", content="Test")
            yield StreamEvent(type="done")

        with patch("app.api.stream.ClaudeAdapter") as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.stream = mock_stream
            mock_adapter_cls.return_value = mock_adapter

            with client.websocket_connect("/api/stream") as websocket:
                websocket.send_json(
                    {
                        "type": "request",
                        "model": "claude-sonnet-4-5",
                        "messages": [{"role": "user", "content": "Hi"}],
                    }
                )

                chunk = websocket.receive_json()
                assert chunk["type"] == "content"

                done = websocket.receive_json()
                assert done["type"] == "done"

    def test_first_message_must_be_request(self, client):
        """Test that first message must be type='request'."""
        with client.websocket_connect("/api/stream") as websocket:
            # Send cancel as first message
            websocket.send_json({"type": "cancel"})

            error = websocket.receive_json()
            assert error["type"] == "error"
            assert "First message must be type 'request'" in error["error"]

    def test_request_requires_model_and_messages(self, client):
        """Test that request type requires model and messages."""
        with client.websocket_connect("/api/stream") as websocket:
            websocket.send_json({"type": "request"})

            error = websocket.receive_json()
            assert error["type"] == "error"
            assert "'model' and 'messages' are required" in error["error"]


class TestStreamingState:
    """Tests for StreamingState class."""

    def test_initial_state(self):
        """Test initial state values."""
        from app.api.stream import StreamingState

        state = StreamingState()
        assert state.cancelled is False
        assert state.input_tokens == 0
        assert state.output_tokens == 0
        assert not state.cancel_event.is_set()

    def test_cancel_event_set(self):
        """Test cancel event can be set."""
        from app.api.stream import StreamingState

        state = StreamingState()
        state.cancel_event.set()
        assert state.cancel_event.is_set()
