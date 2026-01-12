"""End-to-end tests for universal session tracking.

Tests the full flow of session tracking across all endpoints.
Uses mocked database but real API routing.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app


@pytest.fixture
def mock_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def client(mock_session):
    """Test client with mocked database."""

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestSessionsApiFiltering:
    """Tests for sessions API project filtering."""

    def test_list_sessions_filter_by_project(self, client, mock_session):
        """Test filtering sessions by project_id."""
        # Mock session data for portfolio-ai
        mock_db_session = MagicMock()
        mock_db_session.id = "session-1"
        mock_db_session.project_id = "portfolio-ai"
        mock_db_session.provider = "gemini"
        mock_db_session.model = "gemini-3-flash-preview"
        mock_db_session.status = "completed"
        mock_db_session.purpose = "thesis_generation"
        mock_db_session.session_type = "completion"
        mock_db_session.created_at = datetime(2026, 1, 12, 10, 0, 0)
        mock_db_session.updated_at = datetime(2026, 1, 12, 10, 0, 0)

        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        # Mock list query
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [mock_db_session]

        # Mock message count query
        mock_msg_count_result = MagicMock()
        mock_msg_count_result.all.return_value = [("session-1", 3)]

        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_list_result, mock_msg_count_result]
        )

        response = client.get("/api/sessions?project_id=portfolio-ai")

        assert response.status_code == 200
        data = response.json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["project_id"] == "portfolio-ai"
        assert data["sessions"][0]["purpose"] == "thesis_generation"

    def test_list_sessions_filter_by_status(self, client, mock_session):
        """Test filtering by status works."""
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(side_effect=[mock_count_result, mock_list_result])

        response = client.get("/api/sessions?status=active")

        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []

    def test_list_sessions_pagination(self, client, mock_session):
        """Test pagination parameters work."""
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


class TestSessionCreation:
    """Tests for session creation endpoint."""

    def test_create_session_with_project(self, client, mock_session):
        """Test creating a session with project_id."""

        def set_timestamps(obj):
            obj.created_at = datetime.now()
            obj.updated_at = datetime.now()

        mock_session.refresh.side_effect = set_timestamps

        response = client.post(
            "/api/sessions",
            json={
                "project_id": "summitflow",
                "provider": "claude",
                "model": "claude-sonnet-4-5-20250514",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == "summitflow"
        mock_session.add.assert_called_once()

    def test_create_session_with_monkey_fight_project(self, client, mock_session):
        """Test creating a session for monkey-fight project."""

        def set_timestamps(obj):
            obj.created_at = datetime.now()
            obj.updated_at = datetime.now()

        mock_session.refresh.side_effect = set_timestamps

        response = client.post(
            "/api/sessions",
            json={
                "project_id": "monkey-fight",
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == "monkey-fight"

    def test_create_session_missing_provider_fails(self, client):
        """Test validation error for missing provider."""
        response = client.post(
            "/api/sessions",
            json={"project_id": "test", "model": "claude-sonnet-4-5"},
        )
        assert response.status_code == 422


class TestGetSession:
    """Tests for GET session with project info."""

    def test_get_session_includes_project_info(self, client, mock_session):
        """Test that session response includes project_id and purpose."""
        mock_db_session = MagicMock()
        mock_db_session.id = "session-portfolio-123"
        mock_db_session.project_id = "portfolio-ai"
        mock_db_session.provider = "claude"
        mock_db_session.model = "claude-sonnet-4-5"
        mock_db_session.status = "active"
        mock_db_session.purpose = "strategy_generation"
        mock_db_session.session_type = "completion"
        mock_db_session.created_at = datetime(2026, 1, 12, 10, 0, 0)
        mock_db_session.updated_at = datetime(2026, 1, 12, 10, 0, 0)
        mock_db_session.messages = []

        # Session query result
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = mock_db_session

        # Token totals
        mock_token_result = MagicMock()
        mock_token_result.one.return_value = (100, 50)

        # Context query
        mock_context_result = MagicMock()
        mock_context_result.scalar_one_or_none.return_value = None

        mock_session.execute.side_effect = [
            mock_session_result,
            mock_token_result,
            mock_context_result,
        ]

        response = client.get("/api/sessions/session-portfolio-123")

        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == "portfolio-ai"
        assert data["purpose"] == "strategy_generation"


class TestMultiProjectScenario:
    """Tests for multi-project tracking scenario."""

    def test_multiple_projects_list_separately(self, client, mock_session):
        """Verify sessions from different projects can be listed separately."""
        # First request: filter by portfolio-ai
        mock_count_1 = MagicMock()
        mock_count_1.scalar.return_value = 3

        mock_session_1 = MagicMock()
        mock_session_1.id = "port-1"
        mock_session_1.project_id = "portfolio-ai"
        mock_session_1.provider = "gemini"
        mock_session_1.model = "gemini-3-flash-preview"
        mock_session_1.status = "completed"
        mock_session_1.purpose = "thesis_generation"
        mock_session_1.session_type = "completion"
        mock_session_1.created_at = datetime(2026, 1, 12, 10, 0, 0)
        mock_session_1.updated_at = datetime(2026, 1, 12, 10, 0, 0)

        mock_list_1 = MagicMock()
        mock_list_1.scalars.return_value.all.return_value = [mock_session_1]

        mock_msg_count_1 = MagicMock()
        mock_msg_count_1.all.return_value = [("port-1", 5)]

        mock_session.execute = AsyncMock(side_effect=[mock_count_1, mock_list_1, mock_msg_count_1])

        response = client.get("/api/sessions?project_id=portfolio-ai")
        assert response.status_code == 200
        data = response.json()
        assert all(s["project_id"] == "portfolio-ai" for s in data["sessions"])

    def test_sessions_have_purpose_field(self, client, mock_session):
        """Verify purpose field is present in session response."""
        mock_count = MagicMock()
        mock_count.scalar.return_value = 1

        mock_db_session = MagicMock()
        mock_db_session.id = "session-purpose"
        mock_db_session.project_id = "summitflow"
        mock_db_session.provider = "claude"
        mock_db_session.model = "claude-sonnet-4-5"
        mock_db_session.status = "completed"
        mock_db_session.purpose = "mockup_generation"
        mock_db_session.session_type = "completion"
        mock_db_session.created_at = datetime(2026, 1, 12, 10, 0, 0)
        mock_db_session.updated_at = datetime(2026, 1, 12, 10, 0, 0)

        mock_list = MagicMock()
        mock_list.scalars.return_value.all.return_value = [mock_db_session]

        mock_msg_count = MagicMock()
        mock_msg_count.all.return_value = [("session-purpose", 2)]

        mock_session.execute = AsyncMock(side_effect=[mock_count, mock_list, mock_msg_count])

        response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data["sessions"]) == 1
        assert "purpose" in data["sessions"][0]
        assert data["sessions"][0]["purpose"] == "mockup_generation"
