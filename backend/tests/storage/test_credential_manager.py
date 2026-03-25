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

    @pytest.mark.asyncio
    async def test_load_rebuilds_cache_from_source_of_truth(self, mock_db):
        """Repeated load() should clear stale in-memory credentials."""
        fernet = Fernet(TEST_KEY.encode())

        cred1 = MagicMock()
        cred1.provider = "gemini"
        cred1.credential_type = "api_key"
        cred1.value_encrypted = fernet.encrypt(b"old-key")

        cred2 = MagicMock()
        cred2.provider = "gemini"
        cred2.credential_type = "api_key"
        cred2.value_encrypted = fernet.encrypt(b"new-key")

        result1 = MagicMock()
        result1.scalars.return_value.all.return_value = [cred1]
        result2 = MagicMock()
        result2.scalars.return_value.all.return_value = [cred2]
        mock_db.execute.side_effect = [result1, result2]

        manager = CredentialManager.get_instance()
        await manager.load(mock_db)
        await manager.load(mock_db)

        assert manager.get_api_keys("gemini") == ["new-key"]

    @pytest.mark.asyncio
    async def test_load_with_retry_recovers_from_transient_failure(self, mock_db):
        """Boot-time retry should recover from a transient DB/load failure."""
        fernet = Fernet(TEST_KEY.encode())

        mock_credential = MagicMock()
        mock_credential.provider = "gemini"
        mock_credential.credential_type = "api_key"
        mock_credential.value_encrypted = fernet.encrypt(b"gemini-key")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_credential]

        manager = CredentialManager.get_instance()

        class _Session:
            def __init__(self, db):
                self._db = db

            async def __aenter__(self):
                return self._db

            async def __aexit__(self, exc_type, exc, tb):
                return False

        mock_db.execute.side_effect = [RuntimeError("db not ready"), mock_result]

        with patch("app.services.credential_manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            loaded = await manager.load_with_retry(lambda: _Session(mock_db), attempts=2, initial_delay_seconds=0.1)

        assert loaded == 1
        assert manager.get_api_key("gemini") == "gemini-key"
        mock_sleep.assert_awaited_once_with(0.1)

    @pytest.mark.asyncio
    async def test_load_with_retry_raises_after_exhausting_attempts(self, mock_db):
        """Startup must fail visibly when credential cache never becomes available."""
        manager = CredentialManager.get_instance()

        class _Session:
            def __init__(self, db):
                self._db = db

            async def __aenter__(self):
                return self._db

            async def __aexit__(self, exc_type, exc, tb):
                return False

        mock_db.execute.side_effect = RuntimeError("db unavailable")

        with (
            patch("app.services.credential_manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            pytest.raises(RuntimeError, match="Failed to load credentials after 3 attempts"),
        ):
            await manager.load_with_retry(lambda: _Session(mock_db), attempts=3, initial_delay_seconds=0.1)

        assert mock_sleep.await_count == 2


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

    def test_get_api_keys_returns_all_for_provider(self):
        """get_api_keys should return all keys in insertion order."""
        manager = CredentialManager.get_instance()
        manager.set("gemini", "api_key", "key-1")
        manager.set("gemini", "api_key", "key-2")
        assert manager.get_api_keys("gemini") == ["key-1", "key-2"]

    def test_replace_value_updates_in_place_without_stale_key(self):
        """replace_value should keep order and remove stale key values."""
        manager = CredentialManager.get_instance()
        manager.set("gemini", "api_key", "key-1")
        manager.set("gemini", "api_key", "key-2")

        manager.replace_value("gemini", "api_key", "key-1", "key-1-rotated")

        assert manager.get_api_keys("gemini") == ["key-1-rotated", "key-2"]
        assert manager.get_api_key("gemini") == "key-1-rotated"

    def test_remove_value_deletes_single_match(self):
        """remove_value should remove only one key and keep remaining keys."""
        manager = CredentialManager.get_instance()
        manager.set("gemini", "api_key", "key-1")
        manager.set("gemini", "api_key", "key-2")

        manager.remove_value("gemini", "api_key", "key-1")

        assert manager.get_api_keys("gemini") == ["key-2"]
        assert manager.get_api_key("gemini") == "key-2"

    def test_set_api_keys_replaces_order_atomically(self):
        """set_api_keys should overwrite key order and set the new primary."""
        manager = CredentialManager.get_instance()
        manager.set("gemini", "api_key", "key-1")
        manager.set("gemini", "api_key", "key-2")

        manager.set_api_keys("gemini", ["key-2", "key-3"])

        assert manager.get_api_keys("gemini") == ["key-2", "key-3"]
        assert manager.get_api_key("gemini") == "key-2"

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
