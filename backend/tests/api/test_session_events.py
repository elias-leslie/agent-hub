"""Tests for POST /sessions/{id}/events lightweight event creation endpoint."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import get_db
from app.main import app
from app.services.event_storage import get_sequencer
from tests.conftest import APITestClient


@pytest.fixture(autouse=True)
def _reset_sequencer() -> None:
    """Reset the global event sequencer so tests don't leak sequence state."""
    get_sequencer()._sessions.clear()


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def client(mock_db: AsyncMock) -> Generator[APITestClient]:
    """Test client with mocked database."""

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    yield APITestClient(app)
    app.dependency_overrides.clear()


def _mock_session_exists(mock_db: AsyncMock) -> None:
    """Configure mock_db so get_session_or_404 finds a session."""
    mock_session_obj = MagicMock()
    mock_session_obj.id = "test-session-123"
    mock_session_obj.project_id = "test-project"
    mock_session_obj.status = "active"
    mock_session_obj.parent_session_id = None
    mock_session_obj.provider_metadata = {}
    mock_session_obj.updated_at = None

    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = mock_session_obj

    # get_session_or_404 calls execute once, then get_max_turn and get_max_sequence
    turn_result = MagicMock()
    turn_result.scalar_one_or_none.return_value = 3  # current turn

    seq_result = MagicMock()
    seq_result.scalar_one_or_none.return_value = 5  # current max sequence

    mock_db.execute = AsyncMock(side_effect=[session_result, turn_result, seq_result])


@pytest.mark.unit
class TestCreateSessionEvent:
    """Tests for POST /api/sessions/{id}/events."""

    def test_creates_tool_use_event(self, client: APITestClient, mock_db: AsyncMock) -> None:
        """Creates a tool_use event with tool_name and tool_input."""
        _mock_session_exists(mock_db)

        response = client.post(
            "/api/sessions/test-session-123/events",
            json={
                "event_type": "tool_use",
                "tool_name": "Write",
                "tool_input": {"file_path": "/app/auth.py"},
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["session_id"] == "test-session-123"
        assert data["sequence"] == 6  # max_seq (5) + 1
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    def test_creates_bash_event(self, client: APITestClient, mock_db: AsyncMock) -> None:
        """Creates event for Bash tool execution."""
        _mock_session_exists(mock_db)

        response = client.post(
            "/api/sessions/test-session-123/events",
            json={
                "event_type": "tool_use",
                "tool_name": "Bash",
                "tool_input": {"command": "dt pytest --quick"},
                "content": "Running tests",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["session_id"] == "test-session-123"

    def test_session_not_found_returns_404(self, client: APITestClient, mock_db: AsyncMock) -> None:
        """Returns 404 when session doesn't exist."""
        not_found_result = MagicMock()
        not_found_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=not_found_result)

        response = client.post(
            "/api/sessions/nonexistent-id/events",
            json={
                "event_type": "tool_use",
                "tool_name": "Write",
            },
        )

        assert response.status_code == 404

    def test_defaults_event_type_to_tool_use(self, client: APITestClient, mock_db: AsyncMock) -> None:
        """Default event_type is tool_use when not specified."""
        _mock_session_exists(mock_db)

        response = client.post(
            "/api/sessions/test-session-123/events",
            json={
                "tool_name": "Edit",
                "tool_input": {"file_path": "/app/main.py"},
            },
        )

        assert response.status_code == 201
        # Verify the event was stored (add was called)
        mock_db.add.assert_called_once()

    def test_creates_event_with_tool_output(self, client: APITestClient, mock_db: AsyncMock) -> None:
        """Creates event with tool_output for tool_result events."""
        _mock_session_exists(mock_db)

        response = client.post(
            "/api/sessions/test-session-123/events",
            json={
                "event_type": "tool_result",
                "tool_name": "Bash",
                "tool_output": {"exit_code": 0},
            },
        )

        assert response.status_code == 201
