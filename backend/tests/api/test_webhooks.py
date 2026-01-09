"""Tests for webhooks API endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app


@pytest.fixture
def mock_db_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def client(mock_db_session):
    """Test client with mocked database."""

    async def override_get_db():
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def mock_webhook():
    """Create a mock webhook subscription."""
    webhook = MagicMock()
    webhook.id = 1
    webhook.url = "https://example.com/webhook"
    webhook.secret = "test-secret-key-abc123"
    webhook.event_types = ["message", "session_start"]
    webhook.project_id = None
    webhook.description = "Test webhook"
    webhook.is_active = 1
    webhook.created_at = datetime.now()
    webhook.failure_count = 0
    return webhook


class TestCreateWebhook:
    """Tests for POST /api/webhooks."""

    def test_create_webhook_success(self, client, mock_db_session):
        """Test creating a new webhook subscription."""

        def set_timestamps(obj):
            obj.id = 1
            obj.created_at = datetime.now()
            obj.failure_count = 0

        mock_db_session.refresh.side_effect = set_timestamps

        response = client.post(
            "/api/webhooks",
            json={
                "url": "https://example.com/webhook",
                "event_types": ["message", "session_start"],
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["url"] == "https://example.com/webhook"
        assert data["event_types"] == ["message", "session_start"]
        assert "secret" in data  # Secret returned only on create
        assert len(data["secret"]) == 64  # 32 bytes hex
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_awaited_once()

    def test_create_webhook_with_optional_fields(self, client, mock_db_session):
        """Test creating webhook with all optional fields."""

        def set_timestamps(obj):
            obj.id = 1
            obj.created_at = datetime.now()
            obj.failure_count = 0

        mock_db_session.refresh.side_effect = set_timestamps

        response = client.post(
            "/api/webhooks",
            json={
                "url": "https://example.com/webhook",
                "event_types": ["message"],
                "project_id": "proj-123",
                "description": "My webhook",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == "proj-123"
        assert data["description"] == "My webhook"

    def test_create_webhook_invalid_event_type(self, client):
        """Test validation error for invalid event type."""
        response = client.post(
            "/api/webhooks",
            json={
                "url": "https://example.com/webhook",
                "event_types": ["invalid_event"],
            },
        )
        assert response.status_code == 400
        assert "Invalid event type" in response.json()["detail"]

    def test_create_webhook_empty_event_types(self, client):
        """Test validation error for empty event types."""
        response = client.post(
            "/api/webhooks",
            json={
                "url": "https://example.com/webhook",
                "event_types": [],
            },
        )
        assert response.status_code == 422

    def test_create_webhook_invalid_url(self, client):
        """Test validation error for invalid URL."""
        response = client.post(
            "/api/webhooks",
            json={
                "url": "not-a-url",
                "event_types": ["message"],
            },
        )
        assert response.status_code == 422


class TestListWebhooks:
    """Tests for GET /api/webhooks."""

    def test_list_webhooks_empty(self, client, mock_db_session):
        """Test listing webhooks when none exist."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        response = client.get("/api/webhooks")

        assert response.status_code == 200
        assert response.json() == []

    def test_list_webhooks_with_results(self, client, mock_db_session, mock_webhook):
        """Test listing webhooks with results."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_webhook]
        mock_db_session.execute.return_value = mock_result

        response = client.get("/api/webhooks")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == 1
        assert data[0]["url"] == "https://example.com/webhook"
        # Secret should NOT be returned on list
        assert "secret" not in data[0]

    def test_list_webhooks_filter_by_project(self, client, mock_db_session):
        """Test filtering by project_id."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        response = client.get("/api/webhooks?project_id=proj-123")

        assert response.status_code == 200


class TestGetWebhook:
    """Tests for GET /api/webhooks/{webhook_id}."""

    def test_get_webhook_success(self, client, mock_db_session, mock_webhook):
        """Test getting a webhook by ID."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_webhook
        mock_db_session.execute.return_value = mock_result

        response = client.get("/api/webhooks/1")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["url"] == "https://example.com/webhook"
        # Secret should NOT be returned on get
        assert "secret" not in data

    def test_get_webhook_not_found(self, client, mock_db_session):
        """Test 404 for non-existent webhook."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        response = client.get("/api/webhooks/999")

        assert response.status_code == 404
        assert response.json()["detail"] == "Webhook not found"


class TestUpdateWebhook:
    """Tests for PATCH /api/webhooks/{webhook_id}."""

    def test_update_webhook_success(self, client, mock_db_session, mock_webhook):
        """Test updating a webhook."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_webhook
        mock_db_session.execute.return_value = mock_result

        response = client.patch(
            "/api/webhooks/1",
            json={"description": "Updated description", "is_active": False},
        )

        assert response.status_code == 200
        mock_db_session.commit.assert_awaited_once()

    def test_update_webhook_url(self, client, mock_db_session, mock_webhook):
        """Test updating webhook URL."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_webhook
        mock_db_session.execute.return_value = mock_result

        response = client.patch(
            "/api/webhooks/1",
            json={"url": "https://new.example.com/webhook"},
        )

        assert response.status_code == 200

    def test_update_webhook_event_types(self, client, mock_db_session, mock_webhook):
        """Test updating webhook event types."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_webhook
        mock_db_session.execute.return_value = mock_result

        response = client.patch(
            "/api/webhooks/1",
            json={"event_types": ["error", "complete"]},
        )

        assert response.status_code == 200

    def test_update_webhook_invalid_event_type(self, client, mock_db_session, mock_webhook):
        """Test validation error for invalid event type on update."""
        response = client.patch(
            "/api/webhooks/1",
            json={"event_types": ["invalid_event"]},
        )

        assert response.status_code == 400
        assert "Invalid event type" in response.json()["detail"]

    def test_update_webhook_not_found(self, client, mock_db_session):
        """Test 404 when updating non-existent webhook."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        response = client.patch(
            "/api/webhooks/999",
            json={"description": "test"},
        )

        assert response.status_code == 404


class TestDeleteWebhook:
    """Tests for DELETE /api/webhooks/{webhook_id}."""

    def test_delete_webhook_success(self, client, mock_db_session, mock_webhook):
        """Test successfully deleting a webhook."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_webhook
        mock_db_session.execute.return_value = mock_result

        response = client.delete("/api/webhooks/1")

        assert response.status_code == 204
        mock_db_session.delete.assert_awaited_once()
        mock_db_session.commit.assert_awaited_once()

    def test_delete_webhook_not_found(self, client, mock_db_session):
        """Test 404 when deleting non-existent webhook."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        response = client.delete("/api/webhooks/999")

        assert response.status_code == 404
