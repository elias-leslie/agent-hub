"""Tests for credential manager startup loading."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.services.credential_manager import CredentialManager, get_credential_manager

TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before each test."""
    CredentialManager.reset()
    yield
    CredentialManager.reset()


@pytest.fixture
def mock_db():
    """Create mock async database session."""
    return AsyncMock()


@pytest.fixture(autouse=True)
def mock_encryption():
    """Mock encryption settings."""
    with patch("app.storage.credentials.settings") as mock_settings:
        mock_settings.agent_hub_encryption_key = TEST_KEY
        yield mock_settings


class TestCredentialManagerSingleton:
    """Tests for singleton pattern."""

    def test_singleton_returns_same_instance(self):
        """Multiple calls should return same instance."""
        instance1 = CredentialManager.get_instance()
        instance2 = CredentialManager.get_instance()
        assert instance1 is instance2

    def test_get_credential_manager_returns_singleton(self):
        """get_credential_manager should return singleton."""
        instance1 = get_credential_manager()
        instance2 = get_credential_manager()
        assert instance1 is instance2

    def test_reset_clears_singleton(self):
        """Reset should clear singleton for testing."""
        instance1 = CredentialManager.get_instance()
        CredentialManager.reset()
        instance2 = CredentialManager.get_instance()
        assert instance1 is not instance2


class TestCredentialManagerLoad:
    """Tests for loading credentials at startup."""

    @pytest.mark.asyncio
    async def test_load_credentials_from_db(self, mock_db):
        """Test loading credentials populates cache."""
        fernet = Fernet(TEST_KEY.encode())
        encrypted = fernet.encrypt(b"sk-ant-test123")

        mock_credential = MagicMock()
        mock_credential.provider = "claude"
        mock_credential.credential_type = "api_key"
        mock_credential.value_encrypted = encrypted

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_credential]
        mock_db.execute.return_value = mock_result

        manager = CredentialManager.get_instance()
        loaded = await manager.load(mock_db)

        assert loaded == 1
        assert manager.get("claude", "api_key") == "sk-ant-test123"
        assert manager.is_initialized is True

    @pytest.mark.asyncio
    async def test_load_multiple_credentials(self, mock_db):
        """Test loading multiple credentials."""
        fernet = Fernet(TEST_KEY.encode())

        mock_cred1 = MagicMock()
        mock_cred1.provider = "claude"
        mock_cred1.credential_type = "api_key"
        mock_cred1.value_encrypted = fernet.encrypt(b"claude-key")

        mock_cred2 = MagicMock()
        mock_cred2.provider = "gemini"
        mock_cred2.credential_type = "api_key"
        mock_cred2.value_encrypted = fernet.encrypt(b"gemini-key")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_cred1, mock_cred2]
        mock_db.execute.return_value = mock_result

        manager = CredentialManager.get_instance()
        loaded = await manager.load(mock_db)

        assert loaded == 2
        assert manager.get("claude", "api_key") == "claude-key"
        assert manager.get("gemini", "api_key") == "gemini-key"

    @pytest.mark.asyncio
    async def test_load_empty_database(self, mock_db):
        """Test loading when no credentials exist."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        manager = CredentialManager.get_instance()
        loaded = await manager.load(mock_db)

        assert loaded == 0
        assert manager.is_initialized is True


class TestCredentialManagerCache:
    """Tests for cache operations."""

    def test_get_returns_none_when_not_found(self):
        """Get should return None for missing credentials."""
        manager = CredentialManager.get_instance()
        assert manager.get("claude", "api_key") is None

    def test_set_adds_to_cache(self):
        """Set should add credential to cache."""
        manager = CredentialManager.get_instance()
        manager.set("claude", "api_key", "test-key")
        assert manager.get("claude", "api_key") == "test-key"

    def test_remove_deletes_from_cache(self):
        """Remove should delete credential from cache."""
        manager = CredentialManager.get_instance()
        manager.set("claude", "api_key", "test-key")
        manager.remove("claude", "api_key")
        assert manager.get("claude", "api_key") is None

    def test_remove_nonexistent_is_safe(self):
        """Remove should not error on missing credential."""
        manager = CredentialManager.get_instance()
        manager.remove("nonexistent", "key")  # Should not raise

    def test_get_api_key_convenience(self):
        """get_api_key should be shorthand for get(provider, 'api_key')."""
        manager = CredentialManager.get_instance()
        manager.set("claude", "api_key", "claude-key")
        assert manager.get_api_key("claude") == "claude-key"

    def test_list_providers(self):
        """list_providers should return sorted providers."""
        manager = CredentialManager.get_instance()
        manager.set("gemini", "api_key", "g-key")
        manager.set("claude", "api_key", "c-key")
        manager.set("claude", "oauth_token", "c-token")

        providers = manager.list_providers()
        assert providers == ["claude", "gemini"]


class TestCredentialManagerAdapterIntegration:
    """Tests for adapter integration."""

    def test_adapter_can_get_credential(self):
        """Adapters should be able to get credentials from manager."""
        manager = CredentialManager.get_instance()
        manager.set("claude", "api_key", "sk-ant-real-key")

        # Simulate adapter getting credential
        api_key = manager.get_api_key("claude")
        assert api_key == "sk-ant-real-key"

    def test_cache_survives_after_crud(self):
        """Cache should reflect CRUD operations."""
        manager = CredentialManager.get_instance()

        # Create
        manager.set("claude", "api_key", "initial-key")
        assert manager.get_api_key("claude") == "initial-key"

        # Update
        manager.set("claude", "api_key", "updated-key")
        assert manager.get_api_key("claude") == "updated-key"

        # Delete
        manager.remove("claude", "api_key")
        assert manager.get_api_key("claude") is None
