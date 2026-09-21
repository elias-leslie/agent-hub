"""Process-safe storage and refresh for Agent Hub Codex OAuth credentials."""

from __future__ import annotations

import asyncio

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.codex_auth import (
    CodexAuthError,
    CodexCredentials,
    extract_account_id,
    parse_stored_oauth_token,
    refresh_access_token,
    serialize_stored_oauth_token,
)
from app.db import async_session
from app.models import Credential
from app.services.credential_manager import get_credential_manager
from app.services.credential_upsert import reset_provider_cooldown_after_credential_change
from app.storage.credentials import decrypt_value, encrypt_value

_CODEX_REFRESH_LOCK_KEY = "agent-hub:codex-oauth-refresh:v1"
_process_lock = asyncio.Lock()
_credential_refresh_tasks: set[asyncio.Task[CodexCredentials]] = set()


def _observe_credential_refresh(task: asyncio.Task[CodexCredentials]) -> None:
    _credential_refresh_tasks.discard(task)
    if not task.cancelled():
        task.exception()


def cached_codex_credentials() -> CodexCredentials:
    """Read Agent Hub's database-owned credentials from the process cache."""
    manager = get_credential_manager()
    token_value = manager.get("codex", "oauth_token") or manager.get_api_key("codex")
    refresh_token = manager.get("codex", "refresh_token")
    access_token, expires_at = parse_stored_oauth_token(token_value)
    if not access_token:
        raise RuntimeError("No Codex OAuth token configured")
    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=extract_account_id(access_token),
        expires_at=expires_at,
    )


async def _acquire_refresh_lock(db: AsyncSession) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": _CODEX_REFRESH_LOCK_KEY},
    )


async def _locked_rows(db: AsyncSession) -> dict[str, Credential]:
    rows = (
        await db.scalars(
            select(Credential)
            .where(
                Credential.provider == "codex",
                Credential.credential_type.in_(("oauth_token", "refresh_token")),
            )
            .order_by(Credential.id)
            .with_for_update()
        )
    ).all()
    return {row.credential_type: row for row in rows}


def _credentials_from_rows(rows: dict[str, Credential]) -> CodexCredentials:
    token_row = rows.get("oauth_token")
    refresh_row = rows.get("refresh_token")
    token_value = decrypt_value(token_row.value_encrypted) if token_row else None
    refresh_token = decrypt_value(refresh_row.value_encrypted) if refresh_row else None
    access_token, expires_at = parse_stored_oauth_token(token_value)
    if not access_token:
        raise RuntimeError("No Codex OAuth token configured")
    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=extract_account_id(access_token),
        expires_at=expires_at,
    )


def _write_pair(
    db: AsyncSession,
    rows: dict[str, Credential],
    credentials: CodexCredentials,
) -> tuple[str, str]:
    if not credentials.refresh_token:
        raise CodexAuthError("Codex OAuth response did not include a refresh token")
    values = {
        "oauth_token": serialize_stored_oauth_token(credentials),
        "refresh_token": credentials.refresh_token,
    }
    for credential_type, value in values.items():
        row = rows.get(credential_type)
        if row is None:
            db.add(
                Credential(
                    provider="codex",
                    credential_type=credential_type,
                    value_encrypted=encrypt_value(value),
                )
            )
        else:
            row.value_encrypted = encrypt_value(value)
    return values["oauth_token"], values["refresh_token"]


async def _publish_cache(oauth_token: str, refresh_token: str) -> None:
    manager = get_credential_manager()
    manager.set("codex", "oauth_token", oauth_token)
    manager.set("codex", "refresh_token", refresh_token)
    await reset_provider_cooldown_after_credential_change("codex", "oauth_token")


async def replace_codex_credentials(credentials: CodexCredentials) -> None:
    """Atomically replace Agent Hub's complete Codex OAuth pair."""
    async with _process_lock:
        async with async_session() as db:
            await _acquire_refresh_lock(db)
            rows = await _locked_rows(db)
            oauth_token, refresh_token = _write_pair(db, rows, credentials)
            await db.commit()
        await _publish_cache(oauth_token, refresh_token)


async def _ensure_fresh_under_lock(
    *,
    force_refresh: bool,
    stale_access_token: str | None = None,
    expected_account_id: str | None = None,
    rotation_started: asyncio.Event,
) -> CodexCredentials:
    async with _process_lock:
        async with async_session() as db:
            await _acquire_refresh_lock(db)
            rows = await _locked_rows(db)
            current = _credentials_from_rows(rows)
            if expected_account_id is not None and current.account_id != expected_account_id:
                raise CodexAuthError(
                    "Codex account changed during authentication recovery"
                )
            another_process_refreshed = (
                stale_access_token is not None
                and current.access_token != stale_access_token
                and not current.is_expired
            )
            if another_process_refreshed or (not force_refresh and not current.is_expired):
                oauth_token = serialize_stored_oauth_token(current)
                if not current.refresh_token:
                    raise CodexAuthError("Codex OAuth token has no refresh token")
                refresh_token = current.refresh_token
                await db.rollback()
            else:
                if not current.refresh_token:
                    raise CodexAuthError("Codex OAuth token is expired and has no refresh token")
                rotation_started.set()
                refreshed = await refresh_access_token(current.refresh_token)
                if refreshed.account_id != current.account_id or (
                    expected_account_id is not None
                    and refreshed.account_id != expected_account_id
                ):
                    raise CodexAuthError(
                        "Codex account changed in the authentication refresh response"
                    )
                current = refreshed
                oauth_token, refresh_token = _write_pair(db, rows, refreshed)
                await db.commit()
        await _publish_cache(oauth_token, refresh_token)
        return current


async def ensure_fresh_codex_credentials(
    *,
    force_refresh: bool = False,
    stale_access_token: str | None = None,
    expected_account_id: str | None = None,
) -> CodexCredentials:
    """Return authoritative credentials, refreshing once under a database lock.

    ``stale_access_token`` identifies a request that received an authentication
    rejection. If another process has already replaced that token, its committed
    pair is reused instead of consuming the refresh token again. Once a provider
    refresh begins, it finishes persistence even if the requesting task is canceled.
    """
    cached = cached_codex_credentials()
    if expected_account_id is not None and cached.account_id != expected_account_id:
        raise CodexAuthError(
            "Codex account changed before authentication recovery"
        )
    if not force_refresh and not cached.is_expired:
        return cached

    rotation_started = asyncio.Event()
    operation = asyncio.create_task(
        _ensure_fresh_under_lock(
            force_refresh=force_refresh,
            stale_access_token=stale_access_token,
            expected_account_id=expected_account_id,
            rotation_started=rotation_started,
        )
    )
    _credential_refresh_tasks.add(operation)
    operation.add_done_callback(_observe_credential_refresh)
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        if not rotation_started.is_set():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        raise


async def drain_codex_credential_refreshes() -> None:
    """Finish provider rotations that outlived their requesting tasks."""
    pending = list(_credential_refresh_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
