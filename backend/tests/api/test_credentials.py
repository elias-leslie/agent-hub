"""Tests for credentials API endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app

TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture
def mock_db_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    return session


@pytest.fixture
def client(mock_db_session):
    """Test client with mocked database."""

    async def override_get_db():
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_encryption():
    """Mock encryption settings for all tests."""
    with patch("app.storage.credentials.settings") as mock_settings:
        mock_settings.agent_hub_encryption_key = TEST_KEY
        with patch("app.api.credentials.EncryptionError", Exception):
            yield mock_settings


class TestCreateCredential:
    """Tests for POST /api/credentials."""

    def test_create_credential_success(self, client, mock_db_session):
        """Test creating a new credential."""

        def set_timestamps(obj):
            obj.id = 1
            obj.created_at = datetime.now()
            obj.updated_at = datetime.now()

        mock_db_session.refresh.side_effect = set_timestamps

        response = client.post(
            "/api/credentials",
            json={
                "provider": "claude",
                "credential_type": "api_key",
                "value": "sk-ant-test-12345678901234567890",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["provider"] == "claude"
        assert data["credential_type"] == "api_key"
        # Value should be masked
        assert "sk-a" in data["value_masked"]
        assert "****" in data["value_masked"]
        assert "7890" in data["value_masked"]
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_awaited_once()

    def test_create_credential_invalid_provider(self, client):
        """Test validation error for invalid provider."""
        response = client.post(
            "/api/credentials",
            json={
                "provider": "invalid",
                "credential_type": "api_key",
                "value": "test",
            },
        )
        assert response.status_code == 400
        assert "Invalid provider" in response.json()["detail"]

    def test_create_credential_invalid_type(self, client):
        """Test validation error for invalid credential type."""
        response = client.post(
            "/api/credentials",
            json={
                "provider": "claude",
                "credential_type": "invalid_type",
                "value": "test",
            },
        )
        assert response.status_code == 400
        assert "Invalid credential_type" in response.json()["detail"]

    def test_create_credential_missing_value(self, client):
        """Test validation error for missing value."""
        response = client.post(
            "/api/credentials",
            json={
                "provider": "claude",
                "credential_type": "api_key",
            },
        )
        assert response.status_code == 422


class TestListCredentials:
    """Tests for GET /api/credentials."""

    def test_list_credentials_empty(self, client, mock_db_session):
        """Test listing credentials when none exist."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        response = client.get("/api/credentials")

        assert response.status_code == 200
        data = response.json()
        assert data["credentials"] == []
        assert data["total"] == 0

    def test_list_credentials_with_results(self, client, mock_db_session):
        """Test listing credentials with results."""
        # Create mock credential
        fernet = Fernet(TEST_KEY.encode())
        encrypted = fernet.encrypt(b"sk-ant-test123456789012")

        mock_credential = MagicMock()
        mock_credential.id = 1
        mock_credential.provider = "claude"
        mock_credential.credential_type = "api_key"
        mock_credential.value_encrypted = encrypted
        mock_credential.created_at = datetime.now()
        mock_credential.updated_at = datetime.now()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_credential]
        mock_db_session.execute.return_value = mock_result

        response = client.get("/api/credentials")

        assert response.status_code == 200
        data = response.json()
        assert len(data["credentials"]) == 1
        assert data["credentials"][0]["provider"] == "claude"
        # Value should be masked
        assert "****" in data["credentials"][0]["value_masked"]
        assert data["total"] == 1

    def test_list_credentials_filter_by_provider(self, client, mock_db_session):
        """Test filtering by provider."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        response = client.get("/api/credentials?provider=claude")

        assert response.status_code == 200


class TestGetCredential:
    """Tests for GET /api/credentials/{credential_id}."""

    def test_get_credential_success(self, client, mock_db_session):
        """Test getting a credential by ID."""
        fernet = Fernet(TEST_KEY.encode())
        encrypted = fernet.encrypt(b"sk-ant-secretkey12345")

        mock_credential = MagicMock()
        mock_credential.id = 1
        mock_credential.provider = "claude"
        mock_credential.credential_type = "api_key"
        mock_credential.value_encrypted = encrypted
        mock_credential.created_at = datetime.now()
        mock_credential.updated_at = datetime.now()

        mock_db_session.get.return_value = mock_credential

        response = client.get("/api/credentials/1")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["provider"] == "claude"
        # Value should be masked
        assert "****" in data["value_masked"]

    def test_get_credential_not_found(self, client, mock_db_session):
        """Test 404 for non-existent credential."""
        mock_db_session.get.return_value = None

        response = client.get("/api/credentials/999")

        assert response.status_code == 404
        assert response.json()["detail"] == "Credential not found"


class TestUpdateCredential:
    """Tests for PUT /api/credentials/{credential_id}."""

    def test_update_credential_success(self, client, mock_db_session):
        """Test updating a credential."""
        mock_credential = MagicMock()
        mock_credential.id = 1
        mock_credential.provider = "claude"
        mock_credential.credential_type = "api_key"
        mock_credential.created_at = datetime.now()
        mock_credential.updated_at = datetime.now()

        mock_db_session.get.return_value = mock_credential

        response = client.put(
            "/api/credentials/1",
            json={"value": "new-secret-key-12345678"},
        )

        assert response.status_code == 200
        data = response.json()
        # Value should be masked
        assert "new-" in data["value_masked"]
        assert "****" in data["value_masked"]
        mock_db_session.commit.assert_awaited_once()

    def test_update_credential_not_found(self, client, mock_db_session):
        """Test 404 when updating non-existent credential."""
        mock_db_session.get.return_value = None

        response = client.put(
            "/api/credentials/999",
            json={"value": "new-value"},
        )

        assert response.status_code == 404


class TestDeleteCredential:
    """Tests for DELETE /api/credentials/{credential_id}."""

    def test_delete_credential_success(self, client, mock_db_session):
        """Test successfully deleting a credential."""
        mock_credential = MagicMock()
        mock_credential.id = 1
        mock_db_session.get.return_value = mock_credential

        response = client.delete("/api/credentials/1")

        assert response.status_code == 204
        mock_db_session.delete.assert_awaited_once()
        mock_db_session.commit.assert_awaited_once()

    def test_delete_credential_not_found(self, client, mock_db_session):
        """Test 404 when deleting non-existent credential."""
        mock_db_session.get.return_value = None

        response = client.delete("/api/credentials/999")

        assert response.status_code == 404


class TestValueMasking:
    """Tests for credential value masking."""

    def test_short_value_fully_masked(self, client, mock_db_session):
        """Test that short values are fully masked."""

        def set_timestamps(obj):
            obj.id = 1
            obj.created_at = datetime.now()
            obj.updated_at = datetime.now()

        mock_db_session.refresh.side_effect = set_timestamps

        response = client.post(
            "/api/credentials",
            json={
                "provider": "gemini",
                "credential_type": "api_key",
                "value": "short",  # 5 chars, should be fully masked
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["value_masked"] == "*****"

    def test_long_value_partially_masked(self, client, mock_db_session):
        """Test that long values show first/last 4 chars."""

        def set_timestamps(obj):
            obj.id = 1
            obj.created_at = datetime.now()
            obj.updated_at = datetime.now()

        mock_db_session.refresh.side_effect = set_timestamps

        response = client.post(
            "/api/credentials",
            json={
                "provider": "gemini",
                "credential_type": "api_key",
                "value": "AIzaSyAbcdefghijklmnopqrstuvwxyz",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["value_masked"].startswith("AIza")
        assert data["value_masked"].endswith("wxyz")
        assert "****" in data["value_masked"]
