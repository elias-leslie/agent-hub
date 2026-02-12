"""Tests for credential storage with encryption."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.storage.credentials import (
    EncryptionError,
    decrypt_value,
    delete_credential_async,
    encrypt_value,
    get_credential_by_id_async,
    list_credentials_async,
    store_credential_async,
    update_credential_async,
)

# Generate a valid Fernet key for testing
TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture
def mock_settings() -> Any:
    """Mock settings with test encryption key."""
    with patch("app.storage.credentials.settings") as mock:
        mock.agent_hub_encryption_key = TEST_KEY
        yield mock


@pytest.fixture
def mock_db() -> MagicMock:
    """Mock async database session.

    Uses MagicMock with async methods configured individually
    so sync methods like db.add() work correctly.
    """
    db = MagicMock()
    db.execute = AsyncMock()
    db.get = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


class TestEncryptDecrypt:
    """Tests for encrypt/decrypt functions."""

    def test_encrypt_value_returns_bytes(self, mock_settings: Any) -> None:
        """Encrypted value should be bytes."""
        result = encrypt_value("test-api-key")
        assert isinstance(result, bytes)

    def test_decrypt_value_returns_original(self, mock_settings: Any) -> None:
        """Decrypted value should match original."""
        original = "sk-ant-test-12345"
        encrypted = encrypt_value(original)
        decrypted = decrypt_value(encrypted)
        assert decrypted == original

    def test_encrypted_at_rest(self, mock_settings: Any) -> None:
        """Encrypted bytes should not contain plaintext."""
        plaintext = "my-secret-api-key"
        encrypted = encrypt_value(plaintext)
        assert plaintext.encode() not in encrypted
        assert decrypt_value(encrypted) == plaintext

    def test_encrypt_requires_key(self) -> None:
        """Encryption should fail without key."""
        with patch("app.storage.credentials.settings") as mock:
            mock.agent_hub_encryption_key = ""
            with pytest.raises(EncryptionError, match="not configured"):
                encrypt_value("test")

    def test_decrypt_with_wrong_key_fails(self, mock_settings: Any) -> None:
        """Decryption with wrong key should fail."""
        encrypted = encrypt_value("test-value")
        mock_settings.agent_hub_encryption_key = Fernet.generate_key().decode()
        with pytest.raises(EncryptionError, match="invalid token"):
            decrypt_value(encrypted)


class TestStoreCredentialAsync:
    """Tests for store_credential_async function."""

    @pytest.mark.asyncio
    async def test_store_encrypts_value(
        self, mock_settings: Any, mock_db: MagicMock
    ) -> None:
        """Stored credential should have encrypted value."""
        await store_credential_async(
            mock_db,
            provider="claude",
            credential_type="api_key",
            value="sk-ant-test",
        )
        mock_db.add.assert_called_once()
        credential = mock_db.add.call_args[0][0]
        assert credential.provider == "claude"
        assert credential.credential_type == "api_key"
        assert isinstance(credential.value_encrypted, bytes)
        assert b"sk-ant-test" not in credential.value_encrypted


class TestGetCredentialAsync:
    """Tests for get_credential_by_id_async function."""

    @pytest.mark.asyncio
    async def test_get_returns_credential(
        self, mock_settings: Any, mock_db: MagicMock
    ) -> None:
        """Getting credential by ID should return the credential."""
        mock_credential = MagicMock()
        mock_db.get.return_value = mock_credential

        result = await get_credential_by_id_async(mock_db, 1)
        assert result == mock_credential

    @pytest.mark.asyncio
    async def test_get_returns_none_if_not_found(
        self, mock_settings: Any, mock_db: MagicMock
    ) -> None:
        """Getting nonexistent credential should return None."""
        mock_db.get.return_value = None

        result = await get_credential_by_id_async(mock_db, 999)
        assert result is None


class TestUpdateCredentialAsync:
    """Tests for update_credential_async function."""

    @pytest.mark.asyncio
    async def test_update_encrypts_new_value(
        self, mock_settings: Any, mock_db: MagicMock
    ) -> None:
        """Updating credential should encrypt new value."""
        mock_credential = MagicMock()
        mock_db.get.return_value = mock_credential

        result = await update_credential_async(mock_db, 1, "new-api-key")

        assert result is not None
        assert isinstance(mock_credential.value_encrypted, bytes)
        assert b"new-api-key" not in mock_credential.value_encrypted

    @pytest.mark.asyncio
    async def test_update_returns_none_if_not_found(
        self, mock_settings: Any, mock_db: MagicMock
    ) -> None:
        """Updating nonexistent credential should return None."""
        mock_db.get.return_value = None

        result = await update_credential_async(mock_db, 999, "value")
        assert result is None


class TestDeleteCredentialAsync:
    """Tests for delete_credential_async function."""

    @pytest.mark.asyncio
    async def test_delete_returns_true_on_success(
        self, mock_settings: Any, mock_db: MagicMock
    ) -> None:
        """Deleting credential should return True."""
        mock_credential = MagicMock()
        mock_db.get.return_value = mock_credential

        result = await delete_credential_async(mock_db, 1)

        assert result is True
        mock_db.delete.assert_called_once_with(mock_credential)

    @pytest.mark.asyncio
    async def test_delete_returns_false_if_not_found(
        self, mock_settings: Any, mock_db: MagicMock
    ) -> None:
        """Deleting nonexistent credential should return False."""
        mock_db.get.return_value = None

        result = await delete_credential_async(mock_db, 999)
        assert result is False


class TestListCredentialsAsync:
    """Tests for list_credentials_async function."""

    @pytest.mark.asyncio
    async def test_list_returns_credentials(
        self, mock_settings: Any, mock_db: MagicMock
    ) -> None:
        """Listing credentials should return list."""
        mock_credentials = [MagicMock(), MagicMock()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_credentials
        mock_db.execute.return_value = mock_result

        result = await list_credentials_async(mock_db)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_filters_by_provider(
        self, mock_settings: Any, mock_db: MagicMock
    ) -> None:
        """Listing should filter by provider."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        await list_credentials_async(mock_db, provider="claude")

        mock_db.execute.assert_called_once()
