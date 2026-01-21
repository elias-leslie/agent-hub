"""Tests for feedback API endpoints."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.main import app
from app.models import MessageFeedback
from tests.conftest import APITestClient


@pytest.fixture
def client():
    """Test client with source headers for kill switch compliance."""
    yield APITestClient(app)


@pytest.fixture
def mock_feedback():
    """Create mock feedback."""
    feedback = MagicMock(spec=MessageFeedback)
    feedback.id = 1
    feedback.message_id = "msg-123"
    feedback.session_id = "sess-abc"
    feedback.feedback_type = "positive"
    feedback.category = None
    feedback.details = None
    feedback.created_at = datetime.now(UTC)
    return feedback


class TestCreateFeedback:
    """Tests for POST /api/feedback."""

    def test_create_positive_feedback(self, client, mock_feedback):
        """Create positive feedback."""
        with patch("app.api.feedback.store_feedback_async") as mock_store:
            mock_store.return_value = mock_feedback

            response = client.post(
                "/api/feedback",
                json={"message_id": "msg-123", "feedback_type": "positive"},
            )

            assert response.status_code == 201
            data = response.json()
            assert data["message_id"] == "msg-123"
            assert data["feedback_type"] == "positive"

    def test_create_negative_feedback_with_category(self, client, mock_feedback):
        """Create negative feedback with category."""
        mock_feedback.feedback_type = "negative"
        mock_feedback.category = "incorrect"

        with patch("app.api.feedback.store_feedback_async") as mock_store:
            mock_store.return_value = mock_feedback

            response = client.post(
                "/api/feedback",
                json={
                    "message_id": "msg-123",
                    "feedback_type": "negative",
                    "category": "incorrect",
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert data["feedback_type"] == "negative"
            assert data["category"] == "incorrect"

    def test_create_feedback_with_details(self, client, mock_feedback):
        """Create feedback with details."""
        mock_feedback.details = "Very helpful response"

        with patch("app.api.feedback.store_feedback_async") as mock_store:
            mock_store.return_value = mock_feedback

            response = client.post(
                "/api/feedback",
                json={
                    "message_id": "msg-123",
                    "feedback_type": "positive",
                    "details": "Very helpful response",
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert data["details"] == "Very helpful response"

    def test_create_feedback_with_session_id(self, client, mock_feedback):
        """Create feedback with session ID."""
        with patch("app.api.feedback.store_feedback_async") as mock_store:
            mock_store.return_value = mock_feedback

            response = client.post(
                "/api/feedback",
                json={
                    "message_id": "msg-123",
                    "feedback_type": "positive",
                    "session_id": "sess-abc",
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert data["session_id"] == "sess-abc"

    def test_invalid_feedback_type(self, client):
        """Reject invalid feedback type."""
        response = client.post(
            "/api/feedback",
            json={"message_id": "msg-123", "feedback_type": "invalid"},
        )

        assert response.status_code == 422

    def test_invalid_category(self, client):
        """Reject invalid category."""
        response = client.post(
            "/api/feedback",
            json={
                "message_id": "msg-123",
                "feedback_type": "negative",
                "category": "invalid_category",
            },
        )

        assert response.status_code == 400
        assert "Invalid category" in response.json()["detail"]

    def test_missing_message_id(self, client):
        """Reject missing message_id."""
        response = client.post(
            "/api/feedback",
            json={"feedback_type": "positive"},
        )

        assert response.status_code == 422


class TestGetFeedback:
    """Tests for GET /api/feedback/message/{message_id}."""

    def test_get_feedback_success(self, client, mock_feedback):
        """Get feedback by message ID."""
        with patch("app.api.feedback.get_feedback_by_message_async") as mock_get:
            mock_get.return_value = mock_feedback

            response = client.get("/api/feedback/message/msg-123")

            assert response.status_code == 200
            data = response.json()
            assert data["message_id"] == "msg-123"

    def test_get_feedback_not_found(self, client):
        """Return 404 for nonexistent feedback."""
        with patch("app.api.feedback.get_feedback_by_message_async") as mock_get:
            mock_get.return_value = None

            response = client.get("/api/feedback/message/nonexistent")

            assert response.status_code == 404
            assert response.json()["detail"] == "Feedback not found"


class TestGetStats:
    """Tests for GET /api/feedback/stats."""

    def test_get_stats(self, client):
        """Get feedback statistics."""
        mock_stats = {
            "total_feedback": 10,
            "positive_count": 8,
            "negative_count": 2,
            "positive_rate": 0.8,
            "categories": {"incorrect": 1, "incomplete": 1},
        }

        with patch("app.api.feedback.get_feedback_stats_async") as mock_get:
            mock_get.return_value = mock_stats

            response = client.get("/api/feedback/stats")

            assert response.status_code == 200
            data = response.json()
            assert data["total_feedback"] == 10
            assert data["positive_count"] == 8
            assert data["positive_rate"] == 0.8

    def test_get_stats_with_session_filter(self, client):
        """Get stats filtered by session."""
        mock_stats = {
            "total_feedback": 5,
            "positive_count": 4,
            "negative_count": 1,
            "positive_rate": 0.8,
            "categories": {"unhelpful": 1},
        }

        with patch("app.api.feedback.get_feedback_stats_async") as mock_get:
            mock_get.return_value = mock_stats

            response = client.get("/api/feedback/stats?session_id=sess-abc")

            assert response.status_code == 200
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args[1]
            assert call_kwargs["session_id"] == "sess-abc"

    def test_get_stats_with_days_filter(self, client):
        """Get stats filtered by days."""
        mock_stats = {
            "total_feedback": 3,
            "positive_count": 3,
            "negative_count": 0,
            "positive_rate": 1.0,
            "categories": {},
        }

        with patch("app.api.feedback.get_feedback_stats_async") as mock_get:
            mock_get.return_value = mock_stats

            response = client.get("/api/feedback/stats?days=7")

            assert response.status_code == 200
            call_kwargs = mock_get.call_args[1]
            assert call_kwargs["days"] == 7
