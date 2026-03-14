"""System-managed credential namespaces and helpers."""

from __future__ import annotations

SYSTEM_PROVIDER_PREFIX = "_system_"


def is_system_credential_provider(provider: str) -> bool:
    """Return whether a provider ID is reserved for internal credentials."""
    return provider.startswith(SYSTEM_PROVIDER_PREFIX)
