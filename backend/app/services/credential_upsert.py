"""Credential upsert helpers shared by OAuth flows and admin scripts."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.credential_manager import get_credential_manager
from app.storage.credentials import (
    list_credentials_async,
    store_credential_async,
    update_credential_async,
)

logger = logging.getLogger(__name__)

AUTH_CREDENTIAL_TYPES = {"api_key", "oauth_token", "refresh_token"}


async def reset_provider_cooldown_after_credential_change(provider: str, credential_type: str) -> None:
    """Clear stale provider cooldowns after auth material changes."""
    if credential_type not in AUTH_CREDENTIAL_TYPES:
        return
    try:
        from app.services.agent_routing_completion import reset_provider_rate_limit_cooldown

        await reset_provider_rate_limit_cooldown(provider)
    except Exception:
        logger.warning(
            "failed_to_reset_provider_cooldown_after_credential_change",
            extra={"provider": provider, "credential_type": credential_type},
            exc_info=True,
        )


async def upsert_credential(
    db: AsyncSession,
    provider: str,
    credential_type: str,
    value: str,
) -> None:
    """Store or update a credential in the DB and refresh the in-memory cache."""
    existing = await list_credentials_async(db, provider=provider)
    for cred in existing:
        if cred.credential_type == credential_type:
            await update_credential_async(db, cred.id, value)
            get_credential_manager().set(provider, credential_type, value)
            await reset_provider_cooldown_after_credential_change(provider, credential_type)
            return

    await store_credential_async(db, provider=provider, credential_type=credential_type, value=value)
    get_credential_manager().set(provider, credential_type, value)
    await reset_provider_cooldown_after_credential_change(provider, credential_type)
