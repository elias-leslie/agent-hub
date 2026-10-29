"""Refresh covered synthetic actors without replacing owner-reserved bundles."""

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from app.storage import lab_credentials as storage

REF = "secret://lab/example-local/viewer"


def database(rows):
    db = MagicMock()

    @asynccontextmanager
    async def transaction():
        yield

    db.begin.side_effect = transaction
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: rows)))
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_expired_synthetic_refresh_keeps_reference_and_uses_new_fields():
    past = datetime.now(UTC) - timedelta(days=1)
    row = storage.prepare_lab_credential(
        REF, {"password": os.urandom(16).hex()}, kind="synthetic",
        expires_at=past + timedelta(seconds=1), now=past,
    )
    previous = row.value_encrypted
    db = database([row])
    values = {"password": os.urandom(16).hex(), "session_cookie": os.urandom(16).hex()}
    assert await storage.refresh_lab_credential(db, REF, values) == REF
    assert row.value_encrypted != previous
    assert "LOCK TABLE credentials" in str(db.execute.call_args_list[0].args[0])
    db.add.assert_not_called()
    resolved = await storage.resolve_lab_credentials(
        db, "example-local", [storage.LabCredentialRequest(REF, ("session_cookie",))],
    )
    assert resolved[0].values == {"session_cookie": values["session_cookie"]}


@pytest.mark.parametrize("case", ["missing", "duplicate", "foreign", "temporary", "invalid", "bad-fields"])
@pytest.mark.asyncio
async def test_refresh_refuses_ambiguous_or_owner_reserved_rows_without_change(case):
    row = storage.prepare_lab_credential(
        REF, {"password": os.urandom(16).hex()},
        kind="temporary" if case == "temporary" else "synthetic",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    if case == "foreign":
        row.provider = "_lab_other-local"
    if case == "invalid":
        row.value_encrypted = b"invalid"
    previous = row.value_encrypted
    rows = [] if case == "missing" else [row, row] if case == "duplicate" else [row]
    db = database(rows)
    with pytest.raises(storage.LabCredentialError):
        await storage.refresh_lab_credential(db, REF, {} if case == "bad-fields" else {"password": os.urandom(16).hex()})
    assert row.value_encrypted == previous
    db.flush.assert_not_called()


def test_refresh_cli_routes_private_input_and_sanitizes_errors(tmp_path, monkeypatch):
    from agent_hub_st import lab_credentials as extension
    from agent_hub_st.agents import app

    operation = MagicMock(return_value={"reference": REF})
    monkeypatch.setattr(extension, "_run_local", operation)
    args = ["credentials", "refresh", "--target", "example-local", "--actor", "viewer", "--input", str(tmp_path / "private")]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0
    assert operation.call_args.args == ("refresh",)
    operation.side_effect = RuntimeError("private-error-must-not-escape")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1
    assert "private-error-must-not-escape" not in result.output


@pytest.mark.asyncio
async def test_owner_account_refresh_keeps_the_account_kind():
    row = storage.prepare_lab_credential(REF, {"password": os.urandom(16).hex()}, kind="account")
    db = database([row])
    values = {"username": "viewer", "password": os.urandom(16).hex()}
    assert await storage.refresh_lab_credential(db, REF, values) == REF
    from app.storage.credentials import decrypt_value

    payload = storage.decode_lab_json(decrypt_value(row.value_encrypted))
    assert isinstance(payload, dict)
    assert payload["kind"] == "account"
    assert payload["values"] == values
