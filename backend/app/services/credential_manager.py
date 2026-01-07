"""
Credential manager for loading and caching credentials.

Loads encrypted credentials from database at startup and provides
a centralized cache for adapter consumption.
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Credential
from app.storage.credentials import decrypt_value, EncryptionError

logger = logging.getLogger(__name__)


class CredentialManager:
    """
    Manages credentials with in-memory caching.

    Thread-safe singleton that loads credentials from database
    and caches decrypted values for adapter use.
    """

    _instance: Optional["CredentialManager"] = None
    _initialized: bool = False
    _cache: dict[str, str]

    def __new__(cls) -> "CredentialManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = {}
            cls._instance._initialized = False
        return cls._instance

    @classmethod
    def get_instance(cls) -> "CredentialManager":
        """Get the singleton instance."""
        return cls()

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing."""
        cls._instance = None

    async def load(self, db: AsyncSession) -> int:
        """
        Load all credentials from database into cache.

        Args:
            db: Async database session

        Returns:
            Number of credentials loaded
        """
        try:
            result = await db.execute(select(Credential))
            credentials = result.scalars().all()

            loaded = 0
            for cred in credentials:
                key = f"{cred.provider}:{cred.credential_type}"
                try:
                    self._cache[key] = decrypt_value(cred.value_encrypted)
                    loaded += 1
                except EncryptionError as e:
                    logger.error(f"Failed to decrypt credential {key}: {e}")

            self._initialized = True
            logger.info(f"Loaded {loaded} credentials into cache")
            return loaded

        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")
            raise

    def get(self, provider: str, credential_type: str) -> Optional[str]:
        """
        Get a cached credential value.

        Args:
            provider: Provider name (claude, gemini)
            credential_type: Type (api_key, oauth_token, etc.)

        Returns:
            Decrypted credential value, or None if not found
        """
        key = f"{provider}:{credential_type}"
        return self._cache.get(key)

    def get_api_key(self, provider: str) -> Optional[str]:
        """Convenience method to get api_key for a provider."""
        return self.get(provider, "api_key")

    def set(self, provider: str, credential_type: str, value: str) -> None:
        """
        Update cache when a credential is created/updated.

        Called after CRUD operations to keep cache in sync.
        """
        key = f"{provider}:{credential_type}"
        self._cache[key] = value
        logger.debug(f"Updated credential cache: {key}")

    def remove(self, provider: str, credential_type: str) -> None:
        """
        Remove from cache when a credential is deleted.

        Called after delete operations to keep cache in sync.
        """
        key = f"{provider}:{credential_type}"
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Removed credential from cache: {key}")

    @property
    def is_initialized(self) -> bool:
        """Check if credentials have been loaded."""
        return self._initialized

    def list_providers(self) -> list[str]:
        """List providers with cached credentials."""
        providers = set()
        for key in self._cache:
            provider, _ = key.split(":", 1)
            providers.add(provider)
        return sorted(providers)


# Global instance accessor
def get_credential_manager() -> CredentialManager:
    """Get the credential manager singleton."""
    return CredentialManager.get_instance()
