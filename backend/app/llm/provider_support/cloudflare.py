"""Cloudflare URL helpers (port of pi-mono ``providers/cloudflare.ts``).

Per convergence-map.md D4 and the agent-hub probe of the existing
``backend/app/adapters/cloudflare.py`` (which already proxies to
``OpenAICompatibleAdapter``): Cloudflare Workers AI exposes an
OpenAI-compatible Chat Completions surface. There is no separate
``cloudflare`` API. Cloudflare *models* are catalog entries on
``openai-completions`` with a Cloudflare ``base_url`` and the
``cloudflare-workers-ai`` / ``cloudflare-ai-gateway`` provider
identifier — :mod:`openai_completions` already auto-detects those
identifiers (``send_session_affinity_headers``,
``cf-aig-authorization`` bearer) in its compat layer.

This module exposes only the URL templating helpers pi-mono ships in
``cloudflare.ts``, so other providers (e.g. the Anthropic-via-AI-Gateway
path) can resolve account-templated base URLs.
"""

from __future__ import annotations

import os
import re
from typing import Any

from ..types import Model

# Workers AI direct endpoint.
CLOUDFLARE_WORKERS_AI_BASE_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1"
)
# AI Gateway Unified API. https://developers.cloudflare.com/ai-gateway/usage/unified-api/
CLOUDFLARE_AI_GATEWAY_COMPAT_BASE_URL = (
    "https://gateway.ai.cloudflare.com/v1/{CLOUDFLARE_ACCOUNT_ID}/{CLOUDFLARE_GATEWAY_ID}/compat"
)
# AI Gateway → OpenAI passthrough.
CLOUDFLARE_AI_GATEWAY_OPENAI_BASE_URL = (
    "https://gateway.ai.cloudflare.com/v1/{CLOUDFLARE_ACCOUNT_ID}/{CLOUDFLARE_GATEWAY_ID}/openai"
)
# AI Gateway → Anthropic passthrough.
CLOUDFLARE_AI_GATEWAY_ANTHROPIC_BASE_URL = (
    "https://gateway.ai.cloudflare.com/v1/{CLOUDFLARE_ACCOUNT_ID}/{CLOUDFLARE_GATEWAY_ID}/anthropic"
)


def is_cloudflare_provider(provider: str) -> bool:
    return provider in ("cloudflare-workers-ai", "cloudflare-ai-gateway")


_PLACEHOLDER_RE = re.compile(r"\{([A-Z_][A-Z0-9_]*)\}")


def resolve_cloudflare_base_url(model: Model[Any]) -> str:
    """Substitute ``{VAR}`` placeholders in ``model.base_url`` from environment.

    Mirrors pi-mono's ``resolveCloudflareBaseUrl`` — raises when a required
    env var is missing rather than silently emitting a malformed URL.
    """

    url = model.base_url
    if "{" not in url:
        return url

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        value = os.environ.get(name) or _get_cached_cloudflare_value(name)
        if not value:
            raise RuntimeError(
                f"{name} is required for provider {model.provider} but is not set."
            )
        return value

    return _PLACEHOLDER_RE.sub(_sub, url)


def _get_cached_cloudflare_value(env_name: str) -> str | None:
    credential_type = {
        "CLOUDFLARE_ACCOUNT_ID": "account_id",
        "CLOUDFLARE_GATEWAY_ID": "gateway_id",
    }.get(env_name)
    if credential_type is None:
        return None
    from app.services.credential_manager import get_credential_manager

    return get_credential_manager().get("cloudflare", credential_type)


__all__ = [
    "CLOUDFLARE_AI_GATEWAY_ANTHROPIC_BASE_URL",
    "CLOUDFLARE_AI_GATEWAY_COMPAT_BASE_URL",
    "CLOUDFLARE_AI_GATEWAY_OPENAI_BASE_URL",
    "CLOUDFLARE_WORKERS_AI_BASE_URL",
    "is_cloudflare_provider",
    "resolve_cloudflare_base_url",
]
