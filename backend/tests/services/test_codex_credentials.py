"""Regression tests for Agent Hub-owned Codex credential refresh."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.codex_auth import CodexAuthError, CodexCredentials
from app.services import codex_credentials


def _jwt(*, account_id: str, expires_at: float) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "exp": int(expires_at),
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": account_id,
                },
            }
        ).encode()
    ).rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.sig"


def _credentials(
    access_token: str,
    *,
    refresh_token: str = "refresh",
    account_id: str = "account",
    expires_in: int = 3600,
) -> CodexCredentials:
    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=account_id,
        expires_at=time.time() + expires_in,
    )


def _session_factory(db: MagicMock):
    @asynccontextmanager
    async def _session():
        yield db

    return _session


def test_cached_credentials_use_agent_hub_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_token = _jwt(account_id="database-account", expires_at=time.time() + 3600)
    manager = MagicMock()
    manager.get.side_effect = lambda provider, credential_type: {
        ("codex", "oauth_token"): access_token,
        ("codex", "refresh_token"): "database-refresh",
    }.get((provider, credential_type))
    monkeypatch.setattr(codex_credentials, "get_credential_manager", lambda: manager)

    result = codex_credentials.cached_codex_credentials()

    assert result.access_token == access_token
    assert result.refresh_token == "database-refresh"
    assert result.account_id == "database-account"


@pytest.mark.asyncio
async def test_replace_credentials_updates_pair_before_single_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_row = SimpleNamespace(value_encrypted=b"old-access")
    refresh_row = SimpleNamespace(value_encrypted=b"old-refresh")
    credentials = _credentials("rotated-access", refresh_token="rotated-refresh")
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock()

    async def _commit() -> None:
        stored_access = json.loads(access_row.value_encrypted.decode())
        assert stored_access["access_token"] == "rotated-access"
        assert refresh_row.value_encrypted == b"rotated-refresh"

    db.commit = AsyncMock(side_effect=_commit)
    publish_cache = AsyncMock()
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))
    monkeypatch.setattr(codex_credentials, "_acquire_refresh_lock", AsyncMock())
    monkeypatch.setattr(
        codex_credentials,
        "_locked_rows",
        AsyncMock(
            return_value={
                "oauth_token": access_row,
                "refresh_token": refresh_row,
            }
        ),
    )
    monkeypatch.setattr(codex_credentials, "encrypt_value", lambda value: value.encode())
    monkeypatch.setattr(codex_credentials, "_publish_cache", publish_cache)

    await codex_credentials.replace_codex_credentials(credentials)

    db.commit.assert_awaited_once_with()
    db.add.assert_not_called()
    publish_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_replace_credentials_does_not_publish_cache_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    publish_cache = AsyncMock()
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))
    monkeypatch.setattr(codex_credentials, "_acquire_refresh_lock", AsyncMock())
    monkeypatch.setattr(codex_credentials, "_locked_rows", AsyncMock(return_value={}))
    monkeypatch.setattr(codex_credentials, "encrypt_value", lambda value: value.encode())
    monkeypatch.setattr(codex_credentials, "_publish_cache", publish_cache)

    with pytest.raises(RuntimeError, match="commit failed"):
        await codex_credentials.replace_codex_credentials(
            _credentials("rotated-access", refresh_token="rotated-refresh")
        )

    publish_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejected_stale_token_adopts_pair_rotated_by_another_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _credentials("stale-access", expires_in=-300)
    rotated = _credentials("rotated-access", refresh_token="rotated-refresh")
    db = MagicMock()
    db.execute = AsyncMock()
    db.rollback = AsyncMock()
    refresh = AsyncMock()
    publish = AsyncMock()
    monkeypatch.setattr(codex_credentials, "cached_codex_credentials", lambda: stale)
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))
    monkeypatch.setattr(codex_credentials, "_acquire_refresh_lock", AsyncMock())
    monkeypatch.setattr(codex_credentials, "_locked_rows", AsyncMock(return_value={}))
    monkeypatch.setattr(codex_credentials, "_credentials_from_rows", lambda _rows: rotated)
    monkeypatch.setattr(codex_credentials, "refresh_access_token", refresh)
    monkeypatch.setattr(codex_credentials, "_publish_cache", publish)

    result = await codex_credentials.ensure_fresh_codex_credentials(
        force_refresh=True,
        stale_access_token=stale.access_token,
        expected_account_id="account",
    )

    assert result is rotated
    refresh.assert_not_awaited()
    db.rollback.assert_awaited_once_with()
    publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_rejects_account_change_before_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _credentials("stale-access", expires_in=-300)
    changed = _credentials("changed-access", account_id="other-account")
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    write_pair = MagicMock()
    publish = AsyncMock()
    monkeypatch.setattr(codex_credentials, "cached_codex_credentials", lambda: current)
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))
    monkeypatch.setattr(codex_credentials, "_acquire_refresh_lock", AsyncMock())
    monkeypatch.setattr(codex_credentials, "_locked_rows", AsyncMock(return_value={}))
    monkeypatch.setattr(codex_credentials, "_credentials_from_rows", lambda _rows: current)
    monkeypatch.setattr(
        codex_credentials, "refresh_access_token", AsyncMock(return_value=changed)
    )
    monkeypatch.setattr(codex_credentials, "_write_pair", write_pair)
    monkeypatch.setattr(codex_credentials, "_publish_cache", publish)

    with pytest.raises(CodexAuthError, match="refresh response"):
        await codex_credentials.ensure_fresh_codex_credentials(
            force_refresh=True,
            stale_access_token=current.access_token,
            expected_account_id="account",
        )

    write_pair.assert_not_called()
    db.commit.assert_not_awaited()
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_change_before_recovery_does_not_open_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = _credentials("changed-access", account_id="other-account")
    session = MagicMock()
    monkeypatch.setattr(codex_credentials, "cached_codex_credentials", lambda: changed)
    monkeypatch.setattr(codex_credentials, "async_session", session)

    with pytest.raises(CodexAuthError, match="changed before"):
        await codex_credentials.ensure_fresh_codex_credentials(
            force_refresh=True,
            stale_access_token="rejected-access",
            expected_account_id="account",
        )

    session.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_during_rotation_finishes_commit_and_cache_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _credentials("stale-access", expires_in=-300)
    rotated = _credentials("rotated-access", refresh_token="rotated-refresh")
    commit_started = asyncio.Event()
    release_commit = asyncio.Event()
    db = MagicMock()
    db.execute = AsyncMock()

    async def delayed_commit() -> None:
        commit_started.set()
        await release_commit.wait()

    db.commit = AsyncMock(side_effect=delayed_commit)
    publish = AsyncMock()
    monkeypatch.setattr(codex_credentials, "cached_codex_credentials", lambda: current)
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))
    monkeypatch.setattr(codex_credentials, "_acquire_refresh_lock", AsyncMock())
    monkeypatch.setattr(codex_credentials, "_locked_rows", AsyncMock(return_value={}))
    monkeypatch.setattr(codex_credentials, "_credentials_from_rows", lambda _rows: current)
    monkeypatch.setattr(
        codex_credentials,
        "refresh_access_token",
        AsyncMock(return_value=rotated),
    )
    monkeypatch.setattr(
        codex_credentials,
        "_write_pair",
        MagicMock(return_value=("stored-access", "rotated-refresh")),
    )
    monkeypatch.setattr(codex_credentials, "_publish_cache", publish)

    caller = asyncio.create_task(
        codex_credentials.ensure_fresh_codex_credentials(force_refresh=True)
    )
    await commit_started.wait()
    caller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await caller

    assert codex_credentials._credential_refresh_tasks
    release_commit.set()
    await codex_credentials.drain_codex_credential_refreshes()

    db.commit.assert_awaited_once_with()
    publish.assert_awaited_once_with("stored-access", "rotated-refresh")
