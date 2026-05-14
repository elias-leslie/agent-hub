"""
Credential manager for loading and caching credentials.

Loads encrypted credentials from database at startup and provides
a centralized cache for adapter consumption.

Supports multiple API keys per provider for failover scenarios (e.g.,
Gemini OAuth → key1 → key2).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Credential
from app.storage.credentials import EncryptionError, decrypt_value

logger = logging.getLogger(__name__)


class CredentialManager:
    """
    Manages credentials with in-memory caching.

    Thread-safe singleton that loads credentials from database
    and caches decrypted values for adapter use.

    Supports multiple API keys per provider via ``get_api_keys()``.
    """

    _instance: CredentialManager | None = None
    _initialized: bool = False
    _cache: dict[str, str]
    _multi_cache: dict[str, list[str]]  # provider:type -> [value, ...]

    def __new__(cls) -> CredentialManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = {}
            cls._instance._multi_cache = {}
            cls._instance._initialized = False
        return cls._instance

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        """Return values with duplicates removed while preserving order."""
        seen: set[str] = set()
        out: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    @classmethod
    def get_instance(cls) -> CredentialManager:
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
            # Full reload should rebuild cache from DB source of truth.
            self._cache.clear()
            self._multi_cache.clear()

            result = await db.execute(
                select(Credential).order_by(Credential.id)
            )
            credentials = result.scalars().all()

            loaded = 0
            for cred in credentials:
                key = f"{cred.provider}:{cred.credential_type}"
                try:
                    value = decrypt_value(cred.value_encrypted)
                    # Primary cache: last value wins (backward compat)
                    self._cache[key] = value
                    # Multi cache: collect all values in order
                    self._multi_cache.setdefault(key, []).append(value)
                    loaded += 1
                except EncryptionError as e:
                    logger.error(f"Failed to decrypt credential {key}: {e}")

            self._initialized = True
            logger.info(f"Loaded {loaded} credentials into cache")
            return loaded

        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")
            raise

    async def load_with_retry(
        self,
        db_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        *,
        attempts: int = 5,
        initial_delay_seconds: float = 1.0,
    ) -> int:
        """Load credentials with bounded retry for boot-time DB races.

        This is for runtime startup paths only. We should not keep serving with
        an empty credential cache after a transient boot failure.
        """
        delay_seconds = initial_delay_seconds
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                async with db_factory() as db:
                    loaded = await self.load(db)
                logger.info(
                    "Loaded %d credentials into cache on attempt %d/%d",
                    loaded,
                    attempt,
                    attempts,
                )
                return loaded
            except Exception as e:
                last_error = e
                if attempt >= attempts:
                    break
                logger.warning(
                    "Credential load attempt %d/%d failed: %s; retrying in %.1fs",
                    attempt,
                    attempts,
                    e,
                    delay_seconds,
                )
                await asyncio.sleep(delay_seconds)
                delay_seconds *= 2

        raise RuntimeError(
            f"Failed to load credentials after {attempts} attempts"
        ) from last_error

    def get(self, provider: str, credential_type: str) -> str | None:
        """
        Get a cached credential value.

        Args:
            provider: Provider identifier
            credential_type: Type (api_key, oauth_token, etc.)

        Returns:
            Decrypted credential value, or None if not found
        """
        key = f"{provider}:{credential_type}"
        return self._cache.get(key)

    def get_api_key(self, provider: str) -> str | None:
        """Convenience method to get first api_key for a provider."""
        # Gemini supports multiple API keys and uses ordered failover.
        if provider == "gemini":
            keys = self.get_api_keys(provider)
            if keys:
                return keys[0]
        # Other providers are single-key and use the primary cache value.
        return self.get(provider, "api_key")

    def get_api_keys(self, provider: str) -> list[str]:
        """Return all API keys for a provider in creation order."""
        key = f"{provider}:api_key"
        return list(self._multi_cache.get(key, []))

    def set(self, provider: str, credential_type: str, value: str) -> None:
        """
        Update cache when a credential is created/updated.

        Called after CRUD operations to keep cache in sync.
        """
        key = f"{provider}:{credential_type}"
        self._cache[key] = value
        if provider == "gemini" and credential_type == "api_key":
            # Gemini supports key pools for failover.
            self._multi_cache.setdefault(key, [])
            if value not in self._multi_cache[key]:
                self._multi_cache[key].append(value)
        else:
            # Single-value credential for all non-Gemini provider types.
            self._multi_cache[key] = [value]
        logger.debug(f"Updated credential cache: {key}")

    def set_api_keys(self, provider: str, values: list[str]) -> None:
        """Atomically set ordered API keys for a provider."""
        key = f"{provider}:api_key"
        ordered = self._dedupe(values)
        if not ordered:
            self._multi_cache.pop(key, None)
            self._cache.pop(key, None)
            return
        self._multi_cache[key] = ordered
        self._cache[key] = ordered[0]

    def replace_value(self, provider: str, credential_type: str, old_value: str, new_value: str) -> None:
        """
        Replace one credential value in-place while preserving key order.

        Used for updates so the multi-key cache doesn't retain stale values.
        """
        key = f"{provider}:{credential_type}"
        values = self._multi_cache.get(key)
        if not values:
            self.set(provider, credential_type, new_value)
            return

        try:
            idx = values.index(old_value)
            values[idx] = new_value
        except ValueError:
            values.append(new_value)

        values = self._dedupe(values)
        self._multi_cache[key] = values
        self._cache[key] = values[0] if values else new_value
        logger.debug(f"Replaced credential cache value: {key}")

    def remove(self, provider: str, credential_type: str) -> None:
        """
        Remove from cache when a credential is deleted.

        Called after delete operations to keep cache in sync.
        """
        key = f"{provider}:{credential_type}"
        if key in self._cache:
            del self._cache[key]
        if key in self._multi_cache:
            del self._multi_cache[key]
        logger.debug(f"Removed credential from cache: {key}")

    def remove_value(self, provider: str, credential_type: str, value: str) -> None:
        """
        Remove a specific value from the multi cache.

        Used when deleting one of several API keys for a provider.
        """
        key = f"{provider}:{credential_type}"
        if key in self._multi_cache:
            values = self._multi_cache[key]
            try:
                values.remove(value)
            except ValueError:
                return

            if not values:
                del self._multi_cache[key]
                self._cache.pop(key, None)
            else:
                # Update primary cache to first remaining value
                self._cache[key] = values[0]

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
