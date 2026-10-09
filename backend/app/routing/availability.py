"""Pre-flight route availability: skip routes that cannot serve before calling them.

A model is unavailable when its catalog row is inactive or its provider has no
usable credential. Fallback loops skip such routes with a readable reason
instead of spending an attempt (and a provider error) on them.
"""

from __future__ import annotations

from app.constants.catalog import INACTIVE_MODEL_CATALOG_BY_ID, resolve_model
from app.llm.env_api_keys import get_env_api_key
from app.llm.provider_support.claude_code_cli import claude_cli_signed_in

from .registry import UNKNOWN_PROVIDER, get_provider_for_model

# Providers that authenticate without a stored key.
_KEYLESS_PROVIDERS = frozenset({"local"})


async def route_unavailable_reason(model: str) -> str | None:
    """Return why ``model`` cannot be routed right now, or ``None`` if it can."""
    resolved = resolve_model(model)
    if resolved in INACTIVE_MODEL_CATALOG_BY_ID:
        return f"{resolved} is inactive in the model catalog"
    provider = get_provider_for_model(resolved)
    if provider == UNKNOWN_PROVIDER:
        return f"{resolved} is not in the model catalog"
    if provider in _KEYLESS_PROVIDERS:
        return None
    if provider == "claude":
        if await claude_cli_signed_in():
            return None
        return "Claude Code CLI is not installed or not signed in on this host"
    if get_env_api_key(provider) is None:
        return f"no credential is stored for provider {provider}"
    return None


__all__ = ["route_unavailable_reason"]
