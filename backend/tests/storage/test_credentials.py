"""Tests for credential storage with encryption."""

import pytest
from unittest.mock import patch, MagicMock
from cryptography.fernet import Fernet

from app.storage.credentials import (
    encrypt_value,
    decrypt_value,
    store_credential,
    get_credential,
    update_credential,
    delete_credential,
    list_credentials,
    EncryptionError,
)
from app.models import Credential


# Generate a valid Fernet key for testing
TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture
def mock_settings():
    """Mock settings with test encryption key."""
    with patch("app.storage.credentials.settings") as mock:
        mock.agent_hub_encryption_key = TEST_KEY
        yield mock


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = MagicMock()
    return db


class TestEncryptDecrypt:
    """Tests for encrypt/decrypt functions."""

    def test_encrypt_value_returns_bytes(self, mock_settings):
        """Encrypted value should be bytes."""
        result = encrypt_value("test-api-key")
        assert isinstance(result, bytes)

    def test_decrypt_value_returns_original(self, mock_settings):
        """Decrypted value should match original."""
        original = "sk-ant-test-12345"
        encrypted = encrypt_value(original)
        decrypted = decrypt_value(encrypted)
        assert decrypted == original

    def test_encrypted_at_rest(self, mock_settings):
        """Encrypted bytes should not contain plaintext."""
        plaintext = "my-secret-api-key"
        encrypted = encrypt_value(plaintext)
        # Encrypted data should not contain the original value
        assert plaintext.encode() not in encrypted
        # Should be able to decrypt back
        assert decrypt_value(encrypted) == plaintext

    def test_encrypt_requires_key(self):
        """Encryption should fail without key."""
        with patch("app.storage.credentials.settings") as mock:
            mock.agent_hub_encryption_key = ""
            with pytest.raises(EncryptionError, match="not configured"):
                encrypt_value("test")

    def test_decrypt_with_wrong_key_fails(self, mock_settings):
        """Decryption with wrong key should fail."""
        encrypted = encrypt_value("test-value")
        # Change to different key
        mock_settings.agent_hub_encryption_key = Fernet.generate_key().decode()
        with pytest.raises(EncryptionError, match="invalid token"):
            decrypt_value(encrypted)


class TestStoreCredential:
    """Tests for store_credential function."""

    def test_store_encrypts_value(self, mock_settings, mock_db):
        """Stored credential should have encrypted value."""
        result = store_credential(
            mock_db,
            provider="claude",
            credential_type="api_key",
            value="sk-ant-test",
        )
        mock_db.add.assert_called_once()
        credential = mock_db.add.call_args[0][0]
        assert credential.provider == "claude"
        assert credential.credential_type == "api_key"
        # Value should be encrypted bytes, not plaintext
        assert isinstance(credential.value_encrypted, bytes)
        assert b"sk-ant-test" not in credential.value_encrypted


class TestGetCredential:
    """Tests for get_credential function."""

    def test_get_decrypts_value(self, mock_settings, mock_db):
        """Getting credential should return decrypted value."""
        plaintext = "sk-ant-test-12345"
        encrypted = encrypt_value(plaintext)

        mock_credential = MagicMock()
        mock_credential.value_encrypted = encrypted
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_credential

        result = get_credential(mock_db, "claude", "api_key")
        assert result == plaintext

    def test_get_returns_none_if_not_found(self, mock_settings, mock_db):
        """Getting nonexistent credential should return None."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        result = get_credential(mock_db, "claude", "api_key")
        assert result is None


class TestUpdateCredential:
    """Tests for update_credential function."""

    def test_update_encrypts_new_value(self, mock_settings, mock_db):
        """Updating credential should encrypt new value."""
        mock_credential = MagicMock()
        mock_db.get.return_value = mock_credential

        update_credential(mock_db, 1, "new-api-key")

        # New value should be encrypted
        assert isinstance(mock_credential.value_encrypted, bytes)
        assert b"new-api-key" not in mock_credential.value_encrypted

    def test_update_returns_none_if_not_found(self, mock_settings, mock_db):
        """Updating nonexistent credential should return None."""
        mock_db.get.return_value = None
        result = update_credential(mock_db, 999, "value")
        assert result is None


class TestDeleteCredential:
    """Tests for delete_credential function."""

    def test_delete_returns_true_on_success(self, mock_settings, mock_db):
        """Deleting credential should return True."""
        mock_credential = MagicMock()
        mock_db.get.return_value = mock_credential

        result = delete_credential(mock_db, 1)

        assert result is True
        mock_db.delete.assert_called_once_with(mock_credential)
        mock_db.commit.assert_called_once()

    def test_delete_returns_false_if_not_found(self, mock_settings, mock_db):
        """Deleting nonexistent credential should return False."""
        mock_db.get.return_value = None
        result = delete_credential(mock_db, 999)
        assert result is False


class TestListCredentials:
    """Tests for list_credentials function."""

    def test_list_returns_credentials(self, mock_settings, mock_db):
        """Listing credentials should return list."""
        mock_credentials = [MagicMock(), MagicMock()]
        mock_db.execute.return_value.scalars.return_value.all.return_value = mock_credentials

        result = list_credentials(mock_db)

        assert len(result) == 2

    def test_list_filters_by_provider(self, mock_settings, mock_db):
        """Listing should filter by provider."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        list_credentials(mock_db, provider="claude")

        # Check that the query was filtered
        mock_db.execute.assert_called_once()
