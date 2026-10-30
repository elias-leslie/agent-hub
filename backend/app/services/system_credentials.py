"""System-managed credential namespaces and helpers."""

from __future__ import annotations

SYSTEM_PROVIDER_PREFIX = "_system_"
LAB_PROVIDER_PREFIX = "_lab_"
# Credentials served to remote hosts at tool launch (app.storage.remote_hosts).
HOST_TOOL_PROVIDER_PREFIX = "_host_tool_"


def is_system_credential_provider(provider: str) -> bool:
    """Return whether a provider ID is reserved for internal credentials."""
    return provider.startswith(SYSTEM_PROVIDER_PREFIX)


def is_scoped_credential_provider(provider: str) -> bool:
    """Lab and host-tool rows: never provider keys, never in the provider cache or general API."""
    return provider.startswith((LAB_PROVIDER_PREFIX, HOST_TOOL_PROVIDER_PREFIX))
