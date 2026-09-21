"""Regression tests for process-safe Codex credential selection and refresh."""

from __future__ import annotations

import base64
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.codex_auth import CodexAuthError, CodexAuthTransientError, CodexCredentials
from app.services import codex_credentials


@pytest.fixture(autouse=True)
def _native_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex_credentials.settings, "codex_auth_authority", "native")


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


def _write_native_auth(codex_home: Path, access_token: str, refresh_token: str) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "auth.json").write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                }
            }
        )
    )


def _session_factory(db: MagicMock):
    @asynccontextmanager
    async def _session():
        yield db

    return _session


def test_cached_credentials_prefer_native_auth_over_stale_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    native_access = _jwt(account_id="native-account", expires_at=time.time() + 3600)
    stale_database_access = _jwt(
        account_id="database-account",
        expires_at=time.time() - 300,
    )
    manager = MagicMock()
    manager.get.side_effect = lambda provider, credential_type: {
        ("codex", "oauth_token"): stale_database_access,
        ("codex", "refresh_token"): "stale-database-refresh",
    }.get((provider, credential_type))
    _write_native_auth(tmp_path, native_access, "native-refresh")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(codex_credentials, "get_credential_manager", lambda: manager)

    result = codex_credentials.cached_codex_credentials()

    assert result.access_token == native_access
    assert result.refresh_token == "native-refresh"
    assert result.account_id == "native-account"
    manager.get.assert_not_called()


def test_malformed_native_auth_is_a_transient_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "auth.json").write_text("{malformed")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    with pytest.raises(CodexAuthTransientError, match="temporarily unreadable"):
        codex_credentials.cached_codex_credentials()


def test_missing_native_auth_preserves_database_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_access = _jwt(account_id="database-account", expires_at=time.time() + 3600)
    manager = MagicMock()
    manager.get.side_effect = lambda provider, credential_type: {
        ("codex", "oauth_token"): database_access,
        ("codex", "refresh_token"): "database-refresh",
    }.get((provider, credential_type))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(codex_credentials.settings, "codex_auth_authority", "database")
    monkeypatch.setattr(codex_credentials, "get_credential_manager", lambda: manager)

    result = codex_credentials.cached_codex_credentials()

    assert result.access_token == database_access
    assert result.refresh_token == "database-refresh"
    assert result.account_id == "database-account"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("force_refresh", "initial_expiry"),
    [
        pytest.param(False, -300, id="expired"),
        pytest.param(True, 3600, id="forced"),
    ],
)
async def test_native_refresh_broker_runs_once_and_adopts_rotated_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    force_refresh: bool,
    initial_expiry: int,
) -> None:
    initial_access = _jwt(
        account_id="account",
        expires_at=time.time() + initial_expiry,
    )
    rotated_access = _jwt(account_id="account", expires_at=time.time() + 3600)
    _write_native_auth(tmp_path, initial_access, "initial-refresh")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    async def _refresh_native() -> None:
        _write_native_auth(tmp_path, rotated_access, "rotated-refresh")

    refresh_native = AsyncMock(side_effect=_refresh_native)
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    monkeypatch.setattr(codex_credentials, "refresh_native_codex_auth", refresh_native)
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))

    result = await codex_credentials.ensure_fresh_codex_credentials(
        force_refresh=force_refresh,
        stale_access_token=initial_access,
    )

    refresh_native.assert_awaited_once_with()
    assert result.access_token == rotated_access
    assert result.refresh_token == "rotated-refresh"
    db.rollback.assert_awaited_once_with()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_token_changed_by_another_process_skips_second_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = CodexCredentials(
        access_token="stale-token",
        refresh_token="stale-refresh",
        account_id="account",
        expires_at=time.time() - 300,
    )
    rotated = CodexCredentials(
        access_token="rotated-token",
        refresh_token="rotated-refresh",
        account_id="account",
        expires_at=time.time() + 3600,
    )
    native_credentials = MagicMock(side_effect=[stale, rotated])
    refresh_native = AsyncMock()
    db = MagicMock()
    db.execute = AsyncMock()
    db.rollback = AsyncMock()
    monkeypatch.setattr(codex_credentials, "native_codex_credentials", native_credentials)
    monkeypatch.setattr(codex_credentials, "refresh_native_codex_auth", refresh_native)
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))

    result = await codex_credentials.ensure_fresh_codex_credentials(
        force_refresh=True,
        stale_access_token=stale.access_token,
    )

    assert result is rotated
    refresh_native.assert_not_awaited()
    assert native_credentials.call_count == 2
    db.rollback.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_replace_credentials_updates_pair_before_single_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_row = SimpleNamespace(value_encrypted=b"old-access")
    refresh_row = SimpleNamespace(value_encrypted=b"old-refresh")
    credentials = CodexCredentials(
        access_token="rotated-access",
        refresh_token="rotated-refresh",
        account_id="account",
        expires_at=time.time() + 3600,
    )
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock()

    async def _commit() -> None:
        stored_access = json.loads(access_row.value_encrypted.decode())
        assert stored_access["access_token"] == "rotated-access"
        assert refresh_row.value_encrypted == b"rotated-refresh"

    db.commit = AsyncMock(side_effect=_commit)
    locked_rows = AsyncMock(
        return_value={
            "oauth_token": access_row,
            "refresh_token": refresh_row,
        }
    )
    publish_cache = AsyncMock()
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))
    monkeypatch.setattr(codex_credentials.settings, "codex_auth_authority", "database")
    monkeypatch.setattr(codex_credentials, "_acquire_refresh_lock", AsyncMock())
    monkeypatch.setattr(codex_credentials, "_locked_rows", locked_rows)
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
    credentials = CodexCredentials(
        access_token="rotated-access",
        refresh_token="rotated-refresh",
        account_id="account",
        expires_at=time.time() + 3600,
    )
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    publish_cache = AsyncMock()
    monkeypatch.setattr(codex_credentials.settings, "codex_auth_authority", "database")
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))
    monkeypatch.setattr(codex_credentials, "_acquire_refresh_lock", AsyncMock())
    monkeypatch.setattr(codex_credentials, "_locked_rows", AsyncMock(return_value={}))
    monkeypatch.setattr(codex_credentials, "encrypt_value", lambda value: value.encode())
    monkeypatch.setattr(codex_credentials, "_publish_cache", publish_cache)

    with pytest.raises(RuntimeError, match="commit failed"):
        await codex_credentials.replace_codex_credentials(credentials)

    publish_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_refresh_rejects_unchanged_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = CodexCredentials(
        access_token="rejected-access",
        refresh_token="rejected-refresh",
        account_id="account",
        expires_at=time.time() + 3600,
    )
    db = MagicMock()
    db.execute = AsyncMock()
    db.rollback = AsyncMock()
    monkeypatch.setattr(codex_credentials, "native_codex_credentials", lambda: current)
    monkeypatch.setattr(codex_credentials, "refresh_native_codex_auth", AsyncMock())
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))

    with pytest.raises(CodexAuthTransientError, match="without rotating"):
        await codex_credentials.ensure_fresh_codex_credentials(
            force_refresh=True,
            stale_access_token=current.access_token,
        )


@pytest.mark.asyncio
async def test_native_source_disappearance_does_not_fall_back_to_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = CodexCredentials(
        access_token="expired-access",
        refresh_token="refresh",
        account_id="account",
        expires_at=time.time() - 300,
    )
    db = MagicMock()
    db.execute = AsyncMock()
    monkeypatch.setattr(
        codex_credentials,
        "native_codex_credentials",
        MagicMock(side_effect=[current, None]),
    )
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))
    database = MagicMock()
    monkeypatch.setattr(codex_credentials, "_database_cached_codex_credentials", database)

    with pytest.raises(CodexAuthTransientError, match="disappeared"):
        await codex_credentials.ensure_fresh_codex_credentials()

    database.assert_not_called()


@pytest.mark.asyncio
async def test_native_account_change_is_rejected_during_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = CodexCredentials(
        access_token="stale-access",
        refresh_token="stale-refresh",
        account_id="account-a",
        expires_at=time.time() - 300,
    )
    changed = CodexCredentials(
        access_token="changed-access",
        refresh_token="changed-refresh",
        account_id="account-b",
        expires_at=time.time() + 3600,
    )
    db = MagicMock()
    db.execute = AsyncMock()
    monkeypatch.setattr(
        codex_credentials,
        "native_codex_credentials",
        MagicMock(side_effect=[stale, changed]),
    )
    monkeypatch.setattr(codex_credentials, "async_session", _session_factory(db))

    with pytest.raises(CodexAuthError, match="account changed"):
        await codex_credentials.ensure_fresh_codex_credentials(
            force_refresh=True,
            stale_access_token=stale.access_token,
        )


@pytest.mark.asyncio
async def test_native_account_change_before_recovery_entry_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = CodexCredentials(
        access_token="changed-access",
        refresh_token="changed-refresh",
        account_id="account-b",
        expires_at=time.time() + 3600,
    )
    refresh_native = AsyncMock()
    monkeypatch.setattr(codex_credentials, "native_codex_credentials", lambda: changed)
    monkeypatch.setattr(codex_credentials, "refresh_native_codex_auth", refresh_native)

    with pytest.raises(CodexAuthError, match="changed before"):
        await codex_credentials.ensure_fresh_codex_credentials(
            force_refresh=True,
            stale_access_token="account-a-access",
            expected_account_id="account-a",
        )

    refresh_native.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_account_change_before_recovery_entry_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = CodexCredentials(
        access_token="changed-access",
        refresh_token="changed-refresh",
        account_id="account-b",
        expires_at=time.time() + 3600,
    )
    session = MagicMock()
    monkeypatch.setattr(codex_credentials.settings, "codex_auth_authority", "database")
    monkeypatch.setattr(
        codex_credentials,
        "_database_cached_codex_credentials",
        lambda: changed,
    )
    monkeypatch.setattr(codex_credentials, "async_session", session)

    with pytest.raises(CodexAuthError, match="changed before"):
        await codex_credentials.ensure_fresh_codex_credentials(
            force_refresh=True,
            stale_access_token="account-a-access",
            expected_account_id="account-a",
        )

    session.assert_not_called()
