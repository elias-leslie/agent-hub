"""Credential helpers for non-text provider surfaces."""

from __future__ import annotations

import logging

from app.services.llm_errors import AuthenticationError

logger = logging.getLogger(__name__)


def resolve_api_key(provider_name: str, explicit_key: str | None = None) -> str | None:
    """Try CredentialManager for an API key when no explicit key was supplied."""
    if explicit_key:
        return explicit_key
    try:
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        if cm.is_initialized:
            return cm.get_api_key(provider_name)
    except Exception:
        logger.debug("Credential manager lookup failed for %s", provider_name, exc_info=True)
    return None


def resolve_cloudflare_account_id() -> str:
    """Resolve Cloudflare account ID from CredentialManager."""
    try:
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        if cm.is_initialized:
            account_id = cm.get("cloudflare", "account_id")
            if account_id:
                return account_id
    except Exception:
        logger.debug("Cloudflare credential lookup failed", exc_info=True)
    raise AuthenticationError("cloudflare")
