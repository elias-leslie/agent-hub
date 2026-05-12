"""OAuth provider registry (port of pi-mono ``utils/oauth/index.ts``).

Built-in providers are registered at import; callers use
:func:`get_oauth_provider` / :func:`refresh_oauth_token` /
:func:`get_oauth_api_key` to authenticate.
"""

from __future__ import annotations

import time
from typing import Any

from .anthropic import (
    anthropic_oauth_provider,
    login_anthropic,
    refresh_anthropic_token,
)
from .types import (
    OAuthAuthInfo,
    OAuthCredentials,
    OAuthLoginCallbacks,
    OAuthPrompt,
    OAuthProviderId,
    OAuthProviderInterface,
    OAuthSelectOption,
    OAuthSelectPrompt,
)

_BUILT_IN_OAUTH_PROVIDERS: list[OAuthProviderInterface] = [anthropic_oauth_provider]

_oauth_provider_registry: dict[str, OAuthProviderInterface] = {
    p.id: p for p in _BUILT_IN_OAUTH_PROVIDERS
}


def get_oauth_provider(provider_id: OAuthProviderId) -> OAuthProviderInterface | None:
    return _oauth_provider_registry.get(provider_id)


def register_oauth_provider(provider: OAuthProviderInterface) -> None:
    _oauth_provider_registry[provider.id] = provider


def unregister_oauth_provider(provider_id: str) -> None:
    """Remove ``provider_id`` from the registry.

    Built-in providers are restored to their default implementation; custom
    providers are removed completely (pi-mono parity).
    """

    builtin = next((p for p in _BUILT_IN_OAUTH_PROVIDERS if p.id == provider_id), None)
    if builtin is not None:
        _oauth_provider_registry[provider_id] = builtin
        return
    _oauth_provider_registry.pop(provider_id, None)


def reset_oauth_providers() -> None:
    _oauth_provider_registry.clear()
    for p in _BUILT_IN_OAUTH_PROVIDERS:
        _oauth_provider_registry[p.id] = p


def get_oauth_providers() -> list[OAuthProviderInterface]:
    return list(_oauth_provider_registry.values())


async def refresh_oauth_token(
    provider_id: OAuthProviderId,
    credentials: OAuthCredentials,
) -> OAuthCredentials:
    provider = get_oauth_provider(provider_id)
    if provider is None:
        raise RuntimeError(f"Unknown OAuth provider: {provider_id}")
    return await provider.refresh_token(credentials)


async def get_oauth_api_key(
    provider_id: OAuthProviderId,
    credentials: dict[str, OAuthCredentials],
) -> dict[str, Any] | None:
    """Return ``{"new_credentials": ..., "api_key": ...}`` or ``None``.

    Refreshes ``credentials`` if expired. Raises ``RuntimeError`` if refresh
    fails or the provider is unknown.
    """

    provider = get_oauth_provider(provider_id)
    if provider is None:
        raise RuntimeError(f"Unknown OAuth provider: {provider_id}")

    creds = credentials.get(provider_id)
    if creds is None:
        return None

    if int(time.time() * 1000) >= creds.expires:
        try:
            creds = await provider.refresh_token(creds)
        except Exception as exc:
            raise RuntimeError(f"Failed to refresh OAuth token for {provider_id}") from exc

    return {"new_credentials": creds, "api_key": provider.get_api_key(creds)}


__all__ = [
    "OAuthAuthInfo",
    "OAuthCredentials",
    "OAuthLoginCallbacks",
    "OAuthPrompt",
    "OAuthProviderId",
    "OAuthProviderInterface",
    "OAuthSelectOption",
    "OAuthSelectPrompt",
    "anthropic_oauth_provider",
    "get_oauth_api_key",
    "get_oauth_provider",
    "get_oauth_providers",
    "login_anthropic",
    "refresh_anthropic_token",
    "refresh_oauth_token",
    "register_oauth_provider",
    "reset_oauth_providers",
    "unregister_oauth_provider",
]
