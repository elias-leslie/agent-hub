"""Tests for preferences API endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import UserPreferences


@pytest.fixture
def client():
    """Test client."""
    yield TestClient(app)


class TestGetPreferences:
    """Tests for GET /api/preferences."""

    def test_get_defaults_when_no_prefs(self, client):
        """Return defaults when user has no preferences."""
        with patch("app.api.preferences.get_preferences_async") as mock_get:
            mock_get.return_value = None

            response = client.get("/api/preferences")

            assert response.status_code == 200
            data = response.json()
            assert data["verbosity"] == "normal"
            assert data["tone"] == "professional"
            assert data["default_model"] == "claude-sonnet-4-5"

    def test_get_user_preferences(self, client):
        """Return user preferences when they exist."""
        mock_prefs = MagicMock(spec=UserPreferences)
        mock_prefs.verbosity = "detailed"
        mock_prefs.tone = "friendly"
        mock_prefs.default_model = "claude-sonnet-4-5"

        with patch("app.api.preferences.get_preferences_async") as mock_get:
            mock_get.return_value = mock_prefs

            response = client.get("/api/preferences")

            assert response.status_code == 200
            data = response.json()
            assert data["verbosity"] == "detailed"
            assert data["tone"] == "friendly"

    def test_get_with_user_header(self, client):
        """Use X-User-Id header for user identification."""
        with patch("app.api.preferences.get_preferences_async") as mock_get:
            mock_get.return_value = None

            response = client.get("/api/preferences", headers={"X-User-Id": "user-123"})

            assert response.status_code == 200
            # Verify the mock was called with the correct user_id
            call_args = mock_get.call_args
            assert call_args[0][1] == "user-123"


class TestUpdatePreferences:
    """Tests for PUT /api/preferences."""

    def test_update_verbosity(self, client):
        """Update verbosity preference."""
        mock_prefs = MagicMock(spec=UserPreferences)
        mock_prefs.verbosity = "detailed"
        mock_prefs.tone = "professional"
        mock_prefs.default_model = "claude-sonnet-4-5"

        with patch("app.api.preferences.upsert_preferences_async") as mock_upsert:
            mock_upsert.return_value = mock_prefs

            response = client.put(
                "/api/preferences",
                json={"verbosity": "detailed"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["verbosity"] == "detailed"

    def test_update_tone(self, client):
        """Update tone preference."""
        mock_prefs = MagicMock(spec=UserPreferences)
        mock_prefs.verbosity = "normal"
        mock_prefs.tone = "technical"
        mock_prefs.default_model = "claude-sonnet-4-5"

        with patch("app.api.preferences.upsert_preferences_async") as mock_upsert:
            mock_upsert.return_value = mock_prefs

            response = client.put(
                "/api/preferences",
                json={"tone": "technical"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["tone"] == "technical"

    def test_update_default_model(self, client):
        """Update default model preference."""
        mock_prefs = MagicMock(spec=UserPreferences)
        mock_prefs.verbosity = "normal"
        mock_prefs.tone = "professional"
        mock_prefs.default_model = "claude-opus-4-5"

        with patch("app.api.preferences.upsert_preferences_async") as mock_upsert:
            mock_upsert.return_value = mock_prefs

            response = client.put(
                "/api/preferences",
                json={"default_model": "claude-opus-4-5"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["default_model"] == "claude-opus-4-5"

    def test_update_multiple_fields(self, client):
        """Update multiple preferences at once."""
        mock_prefs = MagicMock(spec=UserPreferences)
        mock_prefs.verbosity = "concise"
        mock_prefs.tone = "friendly"
        mock_prefs.default_model = "claude-haiku-4-5"

        with patch("app.api.preferences.upsert_preferences_async") as mock_upsert:
            mock_upsert.return_value = mock_prefs

            response = client.put(
                "/api/preferences",
                json={
                    "verbosity": "concise",
                    "tone": "friendly",
                    "default_model": "claude-haiku-4-5",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["verbosity"] == "concise"
            assert data["tone"] == "friendly"
            assert data["default_model"] == "claude-haiku-4-5"

    def test_invalid_verbosity(self, client):
        """Reject invalid verbosity value."""
        response = client.put(
            "/api/preferences",
            json={"verbosity": "invalid"},
        )

        assert response.status_code == 400
        assert "Invalid verbosity" in response.json()["detail"]

    def test_invalid_tone(self, client):
        """Reject invalid tone value."""
        response = client.put(
            "/api/preferences",
            json={"tone": "invalid"},
        )

        assert response.status_code == 400
        assert "Invalid tone" in response.json()["detail"]

    def test_invalid_model(self, client):
        """Reject invalid model value."""
        response = client.put(
            "/api/preferences",
            json={"default_model": "gpt-4"},
        )

        assert response.status_code == 400
        assert "Invalid default_model" in response.json()["detail"]
