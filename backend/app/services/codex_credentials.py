"""Process-safe storage and refresh for Agent Hub Codex OAuth credentials."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.codex_auth import (
    CodexAuthError,
    CodexAuthTransientError,
    CodexCredentials,
    extract_account_id,
    parse_stored_oauth_token,
    refresh_access_token,
    serialize_stored_oauth_token,
)
from app.config import settings
from app.db import async_session
from app.models import Credential
from app.services.credential_manager import get_credential_manager
from app.services.credential_upsert import reset_provider_cooldown_after_credential_change
from app.services.native_continuation_runtime import refresh_native_codex_auth
from app.storage.credentials import decrypt_value, encrypt_value

_CODEX_REFRESH_LOCK_KEY = "agent-hub:codex-oauth-refresh:v1"
_process_lock = asyncio.Lock()


def native_codex_auth_path() -> Path:
    root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    return root / "auth.json"


def native_codex_credentials() -> CodexCredentials | None:
    """Read the native Codex-owned OAuth pair without modifying its file."""
    path = native_codex_auth_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexAuthTransientError("Native Codex authentication is temporarily unreadable") from exc
    tokens = payload.get("tokens") if isinstance(payload, dict) else None
    access_token = tokens.get("access_token") if isinstance(tokens, dict) else None
    refresh_token = tokens.get("refresh_token") if isinstance(tokens, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise CodexAuthTransientError("Native Codex authentication has no access token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise CodexAuthTransientError("Native Codex authentication has no refresh token")
    _token, expires_at = parse_stored_oauth_token(access_token)
    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=extract_account_id(access_token),
        expires_at=expires_at,
    )


def _database_cached_codex_credentials() -> CodexCredentials:
    """Read Agent Hub's fallback database credentials from the process cache."""
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


def cached_codex_credentials() -> CodexCredentials:
    """Read credentials from the configured authority without implicit fallback."""
    if settings.codex_auth_authority == "native":
        credentials = native_codex_credentials()
        if credentials is None:
            raise CodexAuthError(
                "Native Codex authentication is unavailable; run `codex login`"
            )
        return credentials
    return _database_cached_codex_credentials()


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
    if settings.codex_auth_authority == "native":
        raise CodexAuthError(
            "Native Codex owns authentication; use `codex login` to replace it"
        )
    async with _process_lock:
        async with async_session() as db:
            await _acquire_refresh_lock(db)
            rows = await _locked_rows(db)
            oauth_token, refresh_token = _write_pair(db, rows, credentials)
            await db.commit()
        await _publish_cache(oauth_token, refresh_token)


async def ensure_fresh_codex_credentials(
    *,
    force_refresh: bool = False,
    stale_access_token: str | None = None,
    expected_account_id: str | None = None,
) -> CodexCredentials:
    """Return authoritative credentials, refreshing once under a database lock.

    ``stale_access_token`` identifies a request that received an authentication
    rejection. If another process has already replaced that token, its committed
    pair is reused instead of consuming the refresh token again.
    """
    if settings.codex_auth_authority == "native":
        native = native_codex_credentials()
        if native is None:
            raise CodexAuthError(
                "Native Codex authentication is unavailable; run `codex login`"
            )
        if expected_account_id is not None and native.account_id != expected_account_id:
            raise CodexAuthError(
                "Native Codex account changed before authentication recovery"
            )
        if not force_refresh and not native.is_expired:
            return native
        async with _process_lock, async_session() as db:
            await _acquire_refresh_lock(db)
            current_native = native_codex_credentials()
            if current_native is None:
                raise CodexAuthTransientError(
                    "Native Codex authentication disappeared during refresh"
                )
            another_process_refreshed = (
                stale_access_token is not None
                and current_native.access_token != stale_access_token
                and current_native.account_id == native.account_id
                and not current_native.is_expired
            )
            if current_native.account_id != native.account_id or (
                expected_account_id is not None
                and current_native.account_id != expected_account_id
            ):
                raise CodexAuthError(
                    "Native Codex account changed during authentication recovery"
                )
            if another_process_refreshed or (
                not force_refresh and not current_native.is_expired
            ):
                await db.rollback()
                return current_native
            before_access_token = current_native.access_token
            try:
                await refresh_native_codex_auth()
            except Exception as exc:
                recovered = native_codex_credentials()
                if recovered is not None and recovered.account_id != native.account_id:
                    raise CodexAuthError(
                        "Native Codex account changed during authentication recovery"
                    ) from exc
                if (
                    recovered is not None
                    and recovered.access_token != before_access_token
                    and not recovered.is_expired
                ):
                    await db.rollback()
                    return recovered
                raise
            refreshed = native_codex_credentials()
            await db.rollback()
            if refreshed is None or refreshed.is_expired:
                raise CodexAuthTransientError(
                    "Native Codex did not produce a usable refreshed token"
                )
            if refreshed.account_id != native.account_id:
                raise CodexAuthError(
                    "Native Codex account changed during authentication recovery"
                )
            if (
                refreshed.access_token == before_access_token
                and refreshed.refresh_token == current_native.refresh_token
            ):
                raise CodexAuthTransientError(
                    "Native Codex returned without rotating the rejected credential"
                )
            return refreshed

    cached = _database_cached_codex_credentials()
    if expected_account_id is not None and cached.account_id != expected_account_id:
        raise CodexAuthError(
            "Codex account changed before authentication recovery"
        )
    if not force_refresh and not cached.is_expired:
        return cached

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
                current = await refresh_access_token(current.refresh_token)
                oauth_token, refresh_token = _write_pair(db, rows, current)
                await db.commit()
        await _publish_cache(oauth_token, refresh_token)
        return current
