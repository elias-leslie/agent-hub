"""Shared state store for pending OAuth flows and credential upsert helper."""

from __future__ import annotations

import asyncio
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.credential_manager import get_credential_manager
from app.storage.credentials import store_credential_async

# In-memory pending flow store (state -> flow data, TTL 10 min)
_pending_flows: dict[str, dict[str, object]] = {}
_FLOW_TTL = 600  # 10 minutes

# Track active callback servers so we don't start duplicates
_active_servers: dict[str, asyncio.Server] = {}

# Hold references to background tasks to prevent GC
_background_tasks: set[asyncio.Task[None]] = set()


def cleanup_expired_flows() -> None:
    """Remove flows older than TTL."""
    now = time.time()
    expired = [k for k, v in _pending_flows.items() if now - float(v.get("created_at", 0)) > _FLOW_TTL]
    for k in expired:
        _pending_flows.pop(k, None)


def get_pending_flow(state: str) -> dict[str, object] | None:
    """Return flow data for the given state, or None."""
    return _pending_flows.get(state)


def set_pending_flow(state: str, provider: str, code_verifier: str) -> None:
    """Register a new pending flow."""
    _pending_flows[state] = {
        "provider": provider,
        "code_verifier": code_verifier,
        "created_at": time.time(),
    }


def pop_pending_flow(state: str) -> None:
    """Remove a pending flow."""
    _pending_flows.pop(state, None)


def cancel_active_server(provider: str) -> None:
    """Stop any active callback server for the provider."""
    server = _active_servers.pop(provider, None)
    if server is not None:
        server.close()


def register_server(provider: str, server: asyncio.Server) -> None:
    """Register an active callback server."""
    _active_servers[provider] = server


def unregister_server(provider: str) -> None:
    """Remove an active callback server entry."""
    _active_servers.pop(provider, None)


def spawn_background_task(coro: asyncio.coroutines.Coroutine[object, object, None]) -> None:  # type: ignore[type-arg]
    """Create a background task and keep a reference to prevent GC."""
    task: asyncio.Task[None] = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def upsert_credential(
    db: AsyncSession,
    provider: str,
    credential_type: str,
    value: str,
) -> None:
    """Store or update a credential in the DB and refresh the cache."""
    from app.storage.credentials import list_credentials_async, update_credential_async

    existing = await list_credentials_async(db, provider=provider)
    for cred in existing:
        if cred.credential_type == credential_type:
            await update_credential_async(db, cred.id, value)
            get_credential_manager().set(provider, credential_type, value)
            return

    await store_credential_async(db, provider=provider, credential_type=credential_type, value=value)
    get_credential_manager().set(provider, credential_type, value)
