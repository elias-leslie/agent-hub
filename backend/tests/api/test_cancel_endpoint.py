"""Tests for REST streaming cancellation endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.stream_registry import StreamRegistry, StreamState


@pytest.fixture
def mock_stream_state():
    """Create a mock stream state."""
    return StreamState(
        session_id="test-session-123",
        model="claude-sonnet-4-5",
        started_at="2024-01-01T00:00:00",
        input_tokens=100,
        output_tokens=50,
        cancelled=False,
        cancelled_at=None,
    )


@pytest.fixture
def mock_cancelled_state():
    """Create a mock cancelled stream state."""
    return StreamState(
        session_id="test-session-123",
        model="claude-sonnet-4-5",
        started_at="2024-01-01T00:00:00",
        input_tokens=100,
        output_tokens=50,
        cancelled=True,
        cancelled_at="2024-01-01T00:01:00",
    )


class TestCancelEndpoint:
    """Tests for POST /sessions/{id}/cancel endpoint."""

    @pytest.mark.asyncio
    async def test_cancel_active_stream(self, mock_stream_state, mock_cancelled_state):
        """Test cancelling an active stream."""
        mock_registry = MagicMock(spec=StreamRegistry)
        mock_registry.get_stream = AsyncMock(return_value=mock_stream_state)
        mock_registry.cancel_stream = AsyncMock(return_value=mock_cancelled_state)

        with patch("app.api.sessions.get_stream_registry", return_value=mock_registry):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/sessions/test-session-123/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test-session-123"
        assert data["cancelled"] is True
        assert data["input_tokens"] == 100
        assert data["output_tokens"] == 50
        assert data["message"] == "Stream cancellation requested"

    @pytest.mark.asyncio
    async def test_cancel_no_active_stream(self):
        """Test 409 when no active stream exists."""
        mock_registry = MagicMock(spec=StreamRegistry)
        mock_registry.get_stream = AsyncMock(return_value=None)

        with patch("app.api.sessions.get_stream_registry", return_value=mock_registry):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/sessions/no-such-session/cancel")

        assert response.status_code == 409
        assert "No active stream" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled(self, mock_cancelled_state):
        """Test cancelling an already cancelled stream."""
        mock_registry = MagicMock(spec=StreamRegistry)
        mock_registry.get_stream = AsyncMock(return_value=mock_cancelled_state)

        with patch("app.api.sessions.get_stream_registry", return_value=mock_registry):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/sessions/test-session-123/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["cancelled"] is True
        assert data["message"] == "Stream was already cancelled"

    @pytest.mark.asyncio
    async def test_cancel_failure(self, mock_stream_state):
        """Test 409 when cancellation fails."""
        mock_registry = MagicMock(spec=StreamRegistry)
        mock_registry.get_stream = AsyncMock(return_value=mock_stream_state)
        mock_registry.cancel_stream = AsyncMock(return_value=None)

        with patch("app.api.sessions.get_stream_registry", return_value=mock_registry):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/sessions/test-session-123/cancel")

        assert response.status_code == 409
        assert "Failed to cancel" in response.json()["detail"]


class TestStreamState:
    """Tests for StreamState dataclass."""

    def test_stream_state_creation(self):
        """Test creating a StreamState."""
        state = StreamState(
            session_id="session-1",
            model="claude-sonnet-4-5",
            started_at="2024-01-01T00:00:00",
        )
        assert state.session_id == "session-1"
        assert state.cancelled is False
        assert state.cancelled_at is None
        assert state.input_tokens == 0
        assert state.output_tokens == 0

    def test_stream_state_to_dict(self):
        """Test converting StreamState to dictionary."""
        state = StreamState(
            session_id="session-1",
            model="claude-sonnet-4-5",
            started_at="2024-01-01T00:00:00",
            input_tokens=100,
            output_tokens=50,
            cancelled=True,
            cancelled_at="2024-01-01T00:01:00",
        )
        d = state.to_dict()
        assert d["session_id"] == "session-1"
        assert d["cancelled"] is True
        assert d["cancelled_at"] == "2024-01-01T00:01:00"

    def test_stream_state_from_dict(self):
        """Test creating StreamState from dictionary."""
        d = {
            "session_id": "session-1",
            "model": "claude-sonnet-4-5",
            "started_at": "2024-01-01T00:00:00",
            "input_tokens": 100,
            "output_tokens": 50,
            "cancelled": True,
            "cancelled_at": "2024-01-01T00:01:00",
        }
        state = StreamState.from_dict(d)
        assert state.session_id == "session-1"
        assert state.cancelled is True
        assert state.input_tokens == 100


class TestStreamRegistry:
    """Tests for StreamRegistry service (unit tests without Redis)."""

    @pytest.mark.asyncio
    async def test_registry_register_graceful_on_error(self):
        """Test that register_stream returns state even on Redis error."""
        # This tests the graceful fallback when Redis is unavailable
        from app.services.stream_registry import StreamRegistry

        registry = StreamRegistry(redis_url="redis://invalid:1234/0")
        # Should not raise, returns state anyway
        state = await registry.register_stream("test-session", "test-model")
        assert state.session_id == "test-session"
        assert state.model == "test-model"
