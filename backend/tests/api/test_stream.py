"""Tests for WebSocket streaming endpoint."""

from unittest.mock import MagicMock, patch

import pytest

from app.adapters.base import StreamEvent
from app.main import app
from tests.conftest import APITestClient


@pytest.fixture
def client():
    """Test client with source headers for kill switch compliance."""
    return APITestClient(app)


class TestStreamEndpoint:
    """Tests for WebSocket /api/stream endpoint."""

    def test_stream_invalid_json(self, client):
        """Test error on invalid JSON."""
        with client.websocket_connect("/api/stream") as websocket:
            websocket.send_text("not valid json")
            data = websocket.receive_json()
            assert data["type"] == "error"
            assert "Invalid request" in data["error"]

    def test_stream_missing_model(self, client):
        """Test error on missing model field."""
        with client.websocket_connect("/api/stream") as websocket:
            websocket.send_json({"messages": [{"role": "user", "content": "hi"}]})
            data = websocket.receive_json()
            assert data["type"] == "error"
            assert "'model' and 'messages' are required" in data["error"]

    def test_stream_missing_messages(self, client):
        """Test error on missing messages field."""
        with client.websocket_connect("/api/stream") as websocket:
            websocket.send_json({"model": "claude-sonnet-4-5"})
            data = websocket.receive_json()
            assert data["type"] == "error"
            assert "'model' and 'messages' are required" in data["error"]

    def test_stream_success(self, client):
        """Test successful streaming completion."""

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="content", content="Hello")
            yield StreamEvent(type="content", content=" world!")
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
                websocket.send_json(
                    {
                        "model": "claude-sonnet-4-5",
                        "messages": [{"role": "user", "content": "Hi"}],
                    }
                )

                # Skip the connected message
                connected = websocket.receive_json()
                assert connected["type"] == "connected"

                # Receive content chunks
                chunk1 = websocket.receive_json()
                assert chunk1["type"] == "content"
                assert chunk1["content"] == "Hello"

                chunk2 = websocket.receive_json()
                assert chunk2["type"] == "content"
                assert chunk2["content"] == " world!"

                # Receive done event
                done = websocket.receive_json()
                assert done["type"] == "done"
                assert done["input_tokens"] == 10
                assert done["output_tokens"] == 5
                assert done["finish_reason"] == "end_turn"

    def test_stream_with_parameters(self, client):
        """Test streaming with custom parameters."""

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="content", content="Test")
            yield StreamEvent(type="done")

        mock_adapter = MagicMock()
        mock_adapter.stream = mock_stream

        with (
            patch("app.api.stream._get_adapter", return_value=mock_adapter),
            client.websocket_connect("/api/stream") as websocket,
        ):
            websocket.send_json(
                {
                    "model": "claude-sonnet-4-5",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1000,
                    "temperature": 0.5,
                    "session_id": "test-session-123",
                }
            )

            # Skip the connected message
            connected = websocket.receive_json()
            assert connected["type"] == "connected"

            # Should receive content and done
            chunk = websocket.receive_json()
            assert chunk["type"] == "content"

            done = websocket.receive_json()
            assert done["type"] == "done"

    def test_stream_error_from_provider(self, client):
        """Test error handling from provider."""

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="error", error="Rate limit exceeded")

        mock_adapter = MagicMock()
        mock_adapter.stream = mock_stream

        with (
            patch("app.api.stream._get_adapter", return_value=mock_adapter),
            client.websocket_connect("/api/stream") as websocket,
        ):
            websocket.send_json(
                {
                    "model": "claude-sonnet-4-5",
                    "messages": [{"role": "user", "content": "Hi"}],
                }
            )

            # Skip the connected message
            connected = websocket.receive_json()
            assert connected["type"] == "connected"

            error = websocket.receive_json()
            assert error["type"] == "error"
            assert "Rate limit" in error["error"]

    def test_stream_gemini_model(self, client):
        """Test routing to Gemini adapter."""

        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="content", content="Gemini response")
            yield StreamEvent(type="done")

        with patch("app.api.stream.GeminiAdapter") as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.stream = mock_stream
            mock_adapter_cls.return_value = mock_adapter

            with client.websocket_connect("/api/stream") as websocket:
                websocket.send_json(
                    {
                        "model": "gemini-3-flash",
                        "messages": [{"role": "user", "content": "Hi"}],
                    }
                )

                # Skip the connected message
                connected = websocket.receive_json()
                assert connected["type"] == "connected"

                chunk = websocket.receive_json()
                assert chunk["type"] == "content"
                assert chunk["content"] == "Gemini response"

                done = websocket.receive_json()
                assert done["type"] == "done"


class TestStreamEvent:
    """Tests for StreamEvent dataclass."""

    def test_content_event(self):
        """Test content event creation."""
        event = StreamEvent(type="content", content="Hello")
        assert event.type == "content"
        assert event.content == "Hello"
        assert event.input_tokens is None

    def test_done_event(self):
        """Test done event with usage info."""
        event = StreamEvent(
            type="done",
            input_tokens=100,
            output_tokens=50,
            finish_reason="end_turn",
        )
        assert event.type == "done"
        assert event.input_tokens == 100
        assert event.output_tokens == 50
        assert event.finish_reason == "end_turn"

    def test_error_event(self):
        """Test error event."""
        event = StreamEvent(type="error", error="Something went wrong")
        assert event.type == "error"
        assert event.error == "Something went wrong"
