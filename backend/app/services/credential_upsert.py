"""Credential upsert helpers shared by OAuth flows and admin scripts."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.credential_manager import get_credential_manager
from app.storage.credentials import (
    list_credentials_async,
    store_credential_async,
    update_credential_async,
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
            return

    await store_credential_async(db, provider=provider, credential_type=credential_type, value=value)
    get_credential_manager().set(provider, credential_type, value)
