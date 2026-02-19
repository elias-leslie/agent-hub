"""Tests for sessions API endpoints."""

from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.models import CLAUDE_SONNET
from app.db import get_db
from app.main import app
from tests.conftest import APITestClient


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def client(mock_session: AsyncMock) -> Generator[APITestClient]:
    """Test client with mocked database and source headers."""

    async def override_get_db() -> AsyncGenerator[AsyncMock]:
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    yield APITestClient(app)
    app.dependency_overrides.clear()


class TestCreateSession:
    """Tests for POST /api/sessions."""

    @patch(
        "app.constants.VALID_PROJECT_IDS",
        frozenset({"test-project"}),
    )
    def test_create_session_success(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test creating a new session."""

        # Set up refresh to populate timestamps
        def set_timestamps(obj: Any) -> None:
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        mock_session.refresh.side_effect = set_timestamps

        response = client.post(
            "/api/sessions",
            json={
                "project_id": "test-project",
                "provider": "claude",
                "model": "claude-sonnet-4-5-20250514",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["project_id"] == "test-project"
        assert data["provider"] == "claude"
        assert data["model"] == "claude-sonnet-4-5-20250514"
        assert data["status"] == "active"
        assert data["messages"] == []
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()

    def test_create_session_missing_provider(self, client: APITestClient) -> None:
        """Test validation error for missing provider."""
        response = client.post(
            "/api/sessions",
            json={"project_id": "test", "model": CLAUDE_SONNET},
        )
        assert response.status_code == 422

    def test_create_session_missing_model(self, client: APITestClient) -> None:
        """Test validation error for missing model."""
        response = client.post(
            "/api/sessions",
            json={"project_id": "test", "provider": "claude"},
        )
        assert response.status_code == 422


class TestGetSession:
    """Tests for GET /api/sessions/{session_id}."""

    def test_get_session_success(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test getting a session with messages."""
        # Create mock session object
        mock_db_session = MagicMock()
        mock_db_session.id = "test-session-123"
        mock_db_session.project_id = "test-project"
        mock_db_session.provider = "claude"
        mock_db_session.model = CLAUDE_SONNET
        mock_db_session.status = "active"
        mock_db_session.agent_slug = None
        mock_db_session.session_type = "completion"
        mock_db_session.created_at = datetime(2026, 1, 6, 10, 0, 0)
        mock_db_session.updated_at = datetime(2026, 1, 6, 10, 0, 0)

        # Create mock events (replacing old messages)
        mock_event = MagicMock()
        mock_event.id = "1"
        mock_event.event_type = "message"
        mock_event.turn = 1
        mock_event.sequence = 1
        mock_event.role = "user"
        mock_event.content = "Hello"
        mock_event.input_tokens = 5
        mock_event.output_tokens = 0
        mock_event.model = CLAUDE_SONNET
        mock_event.model_used = CLAUDE_SONNET
        mock_event.agent_slug = "coder"
        mock_event.agent_id = "1"
        mock_event.agent_name = "Coder"
        mock_event.created_at = datetime(2026, 1, 6, 10, 0, 0)
        mock_db_session.events = [mock_event]

        # Session query result
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = mock_db_session

        # Token totals query result (0, 0)
        mock_token_totals_result = MagicMock()
        mock_token_totals_result.one.return_value = (0, 0)

        # Latest context query result (None - no context yet)
        mock_latest_context_result = MagicMock()
        mock_latest_context_result.scalar_one_or_none.return_value = None

        # Return different results for each execute call
        mock_session.execute.side_effect = [
            mock_session_result,
            mock_token_totals_result,
            mock_latest_context_result,
        ]

        response = client.get("/api/sessions/test-session-123")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-session-123"
        assert len(data["messages"]) == 1
        assert data["messages"][0]["content"] == "Hello"
        # Verify context_usage is included
        assert "context_usage" in data
        assert data["context_usage"]["used_tokens"] == 0
        assert data["context_usage"]["limit_tokens"] == 200000

    def test_get_session_not_found(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test 404 for non-existent session."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = client.get("/api/sessions/nonexistent-id")

        assert response.status_code == 404
        assert response.json()["message"] == "Session not found"


class TestDeleteSession:
    """Tests for DELETE /api/sessions/{session_id}."""

    def test_delete_session_success(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test successfully deleting a session."""
        mock_db_session = MagicMock()
        mock_db_session.id = "test-session-123"
        mock_db_session.status = "active"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_db_session
        mock_session.execute.return_value = mock_result

        response = client.delete("/api/sessions/test-session-123")

        assert response.status_code == 204
        # Now does hard delete instead of soft delete
        mock_session.delete.assert_awaited_once_with(mock_db_session)
        mock_session.commit.assert_awaited_once()

    def test_delete_session_not_found(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test 404 when deleting non-existent session."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = client.delete("/api/sessions/nonexistent-id")

        assert response.status_code == 404


class TestListSessions:
    """Tests for GET /api/sessions."""

    def test_list_sessions_empty(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test listing sessions when none exist."""
        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        # Mock list query
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(side_effect=[mock_count_result, mock_list_result])

        response = client.get("/api/sessions")

        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 20

    def test_list_sessions_with_results(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test listing sessions with results."""
        # Create mock session
        mock_db_session = MagicMock()
        mock_db_session.id = "session-1"
        mock_db_session.project_id = "test-project"
        mock_db_session.provider = "claude"
        mock_db_session.model = CLAUDE_SONNET
        mock_db_session.status = "active"
        mock_db_session.agent_slug = None
        mock_db_session.session_type = "completion"
        mock_db_session.created_at = datetime(2026, 1, 6, 10, 0, 0)
        mock_db_session.updated_at = datetime(2026, 1, 6, 10, 0, 0)

        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        # Mock list query
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [mock_db_session]

        # Mock message count query
        mock_msg_count_result = MagicMock()
        mock_msg_count_result.all.return_value = [("session-1", 5)]

        # Mock token stats query
        mock_token_stats_result = MagicMock()
        mock_token_stats_result.all.return_value = [
            ("session-1", "user", 100),
            ("session-1", "assistant", 200),
        ]

        mock_session.execute = AsyncMock(
            side_effect=[
                mock_count_result,
                mock_list_result,
                mock_msg_count_result,
                mock_token_stats_result,
            ]
        )

        response = client.get("/api/sessions")

        assert response.status_code == 200
        data = response.json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["id"] == "session-1"
        assert data["sessions"][0]["message_count"] == 5
        assert data["sessions"][0]["total_input_tokens"] == 100
        assert data["sessions"][0]["total_output_tokens"] == 200
        assert data["total"] == 1

    def test_list_sessions_filter_by_project(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test filtering by project_id."""
        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        # Mock list query
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(side_effect=[mock_count_result, mock_list_result])

        response = client.get("/api/sessions?project_id=my-project")

        assert response.status_code == 200

    def test_list_sessions_filter_by_status(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test filtering by status."""
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(side_effect=[mock_count_result, mock_list_result])

        response = client.get("/api/sessions?status=active")

        assert response.status_code == 200

    def test_list_sessions_pagination(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test pagination parameters."""
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 50

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(side_effect=[mock_count_result, mock_list_result])

        response = client.get("/api/sessions?page=3&page_size=10")

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 3
        assert data["page_size"] == 10
        assert data["total"] == 50
