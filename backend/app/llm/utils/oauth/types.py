"""OAuth-provider types (port of pi-mono ``utils/oauth/types.ts``)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ...types import Api, Model


@dataclass(slots=True)
class OAuthCredentials:
    """Pi-mono ``OAuthCredentials`` — refresh + access + expires + extras."""

    refresh: str
    access: str
    expires: int  # Unix ms
    extras: dict[str, Any] = field(default_factory=dict)


OAuthProviderId = str
"""Per pi-mono, OAuth provider IDs are open strings (built-ins include ``"anthropic"``)."""


@dataclass(slots=True)
class OAuthPrompt:
    message: str
    placeholder: str | None = None
    allow_empty: bool = False


@dataclass(slots=True)
class OAuthAuthInfo:
    url: str
    instructions: str | None = None


@dataclass(slots=True)
class OAuthSelectOption:
    id: str
    label: str


@dataclass(slots=True)
class OAuthSelectPrompt:
    message: str
    options: list[OAuthSelectOption]


@dataclass(slots=True)
class OAuthLoginCallbacks:
    """Callbacks invoked by an OAuth login flow.

    Mirrors pi-mono's ``OAuthLoginCallbacks`` interface verbatim
    (camelCase → snake_case per D10).
    """

    on_auth: Callable[[OAuthAuthInfo], None]
    on_prompt: Callable[[OAuthPrompt], Awaitable[str]]
    on_progress: Callable[[str], None] | None = None
    on_manual_code_input: Callable[[], Awaitable[str]] | None = None
    on_select: Callable[[OAuthSelectPrompt], Awaitable[str | None]] | None = None
    signal: asyncio.Event | None = None


@runtime_checkable
class OAuthProviderInterface(Protocol):
    """OAuth provider plug-in interface (Protocol)."""

    id: OAuthProviderId
    name: str
    uses_callback_server: bool

    async def login(self, callbacks: OAuthLoginCallbacks) -> OAuthCredentials:
        """Run the login flow, return credentials to persist."""
        ...

    async def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
        """Refresh expired credentials; return updated credentials to persist."""
        ...

    def get_api_key(self, credentials: OAuthCredentials) -> str:
        """Convert credentials to an API key string for the provider."""
        ...

    def modify_models(
        self,
        models: list[Model[Api]],
        credentials: OAuthCredentials,
    ) -> list[Model[Api]]:
        """Optionally tweak model descriptors (e.g. ``base_url``) using creds.

        Default implementation returns the input unchanged.
        """
        ...


__all__ = [
    "OAuthAuthInfo",
    "OAuthCredentials",
    "OAuthLoginCallbacks",
    "OAuthPrompt",
    "OAuthProviderId",
    "OAuthProviderInterface",
    "OAuthSelectOption",
    "OAuthSelectPrompt",
]
