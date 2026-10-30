"""Remote host registry, tool credential map, grants and the host-token endpoints, against PostgreSQL."""

from __future__ import annotations

import importlib.util
import logging
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import make_url, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.models import Credential, RemoteHost, RemoteToolCredential
from app.storage import remote_hosts as storage

SECRET = "sk-dummy-" + "z" * 24
MIGRATION = Path(__file__).resolve().parents[2] / "alembic/versions/c4f7a1e9d2b6_remote_host_credentials.py"


def _seed_rows() -> list[dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("remote_host_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    keys = ("tool_slug", "name", "command", "config_dir", "env_var", "auth_file", "rotates", "description")
    return [dict(zip(keys, row, strict=True)) for row in module._TOOL_MAP]


def test_seeded_map_serves_only_non_rotating_logins() -> None:
    rows = {(row["tool_slug"], row["name"]): row for row in _seed_rows()}
    assert rows[("claude-code", "oauth-token")]["env_var"] == "CLAUDE_CODE_OAUTH_TOKEN"
    assert rows[("claude-code", "oauth-token")]["rotates"] is False
    assert {name for tool, name in rows if tool == "pi" and not rows[(tool, name)]["rotates"]} == {
        "opencode-go", "minimax",
    }
    assert rows[("pi", "oauth")]["rotates"] is True
    # Codex signs in on the host only; agy stays rotating until verified otherwise.
    assert [row["rotates"] for (tool, _), row in rows.items() if tool in {"codex", "agy"}] == [True, True]
    for row in rows.values():
        assert (row["env_var"] is None) != (row["auth_file"] is None)
        assert row["config_dir"].startswith("~/")


def test_host_tool_rows_stay_out_of_the_provider_cache_and_general_api() -> None:
    from app.api.credentials import _is_visible_credential_provider
    from app.services.credential_manager import CredentialManager

    assert not _is_visible_credential_provider("_host_tool_claude-code")
    with pytest.raises(ValueError):
        CredentialManager().set("_host_tool_claude-code", "oauth-token", SECRET)


def test_host_credential_paths_skip_the_request_logging_middleware() -> None:
    from app.middleware.access_control_paths import is_path_exempt

    assert is_path_exempt("/api/host-credentials/claude-code")
    assert is_path_exempt("/api/host-credentials/tools")
    assert not is_path_exempt("/api/remote-hosts")


@pytest_asyncio.fixture
async def pg_db(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncSession]:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    from app.config import settings

    monkeypatch.setattr(settings, "agent_hub_encryption_key", Fernet.generate_key().decode())
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test")
    engine = create_async_engine(url)
    schema = f"remote_hosts_{uuid4().hex}"
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(text(f"SET LOCAL search_path TO {schema}"))

        def create_tables(sync_connection: Any) -> None:
            for table in (Credential.__table__, RemoteHost.__table__, RemoteToolCredential.__table__):
                sync_connection.execute(CreateTable(table))

        await connection.run_sync(create_tables)
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            for row in _seed_rows():
                session.add(RemoteToolCredential(**row))
            await session.commit()
            yield session
        await transaction.rollback()
    await engine.dispose()


async def test_grant_fetch_revoke_lifecycle(pg_db: AsyncSession) -> None:
    token = await storage.add_host(pg_db, "agent-work")
    assert token.startswith(storage.TOKEN_PREFIX)
    stored_hash = (await pg_db.execute(select(RemoteHost.token_hash))).scalar_one()
    assert token not in stored_hash and stored_hash == storage.hash_token(token)

    host = await storage.authenticate_host(pg_db, token)
    assert host is not None and host.granted_tools == ()
    with pytest.raises(storage.ToolNotGranted):
        await storage.resolve_host_credentials(pg_db, host, "claude-code")

    await storage.set_tool_grant(pg_db, "agent-work", "claude-code", granted=True)
    host = await storage.authenticate_host(pg_db, token)
    assert host is not None and host.granted_tools == ("claude-code",)
    with pytest.raises(storage.RemoteHostMissing):  # granted, but nothing pushed yet
        await storage.resolve_host_credentials(pg_db, host, "claude-code")

    await storage.store_tool_credential(pg_db, "claude-code", "oauth-token", SECRET)
    raw = (await pg_db.execute(select(Credential.value_encrypted))).scalar_one()
    assert SECRET.encode() not in raw
    [delivery] = await storage.resolve_host_credentials(pg_db, host, "claude-code")
    assert (delivery.env_var, delivery.value) == ("CLAUDE_CODE_OAUTH_TOKEN", SECRET)
    assert SECRET not in repr(delivery)
    with pytest.raises(storage.ToolNotGranted):
        await storage.resolve_host_credentials(pg_db, host, "pi")

    await storage.revoke_host(pg_db, "agent-work")
    assert await storage.authenticate_host(pg_db, token) is None
    [summary] = await storage.list_hosts(pg_db)
    assert summary.revoked_at is not None and summary.granted_tools == ()

    fresh = await storage.add_host(pg_db, "agent-work")
    assert fresh != token
    assert await storage.authenticate_host(pg_db, token) is None
    readmitted = await storage.authenticate_host(pg_db, fresh)
    assert readmitted is not None and readmitted.granted_tools == ()


async def test_deny_stops_fetches_and_rotating_rows_are_never_stored(pg_db: AsyncSession) -> None:
    token = await storage.add_host(pg_db, "agent-work")
    with pytest.raises(storage.RemoteHostExists):
        await storage.add_host(pg_db, "agent-work")
    with pytest.raises(storage.RemoteHostMissing):
        await storage.set_tool_grant(pg_db, "agent-work", "no-such-tool", granted=True)
    with pytest.raises(storage.RemoteHostError):
        await storage.store_tool_credential(pg_db, "codex", "login", SECRET)
    with pytest.raises(storage.RemoteHostError):
        await storage.store_tool_credential(pg_db, "pi", "oauth", SECRET)

    await storage.set_tool_grant(pg_db, "agent-work", "pi", granted=True)
    await storage.store_tool_credential(pg_db, "pi", "opencode-go", SECRET)
    host = await storage.authenticate_host(pg_db, token)
    assert host is not None
    assert [item.env_var for item in await storage.resolve_host_credentials(pg_db, host, "pi")] == [
        "OPENCODE_API_KEY",
    ]

    await storage.set_tool_grant(pg_db, "agent-work", "pi", granted=False)
    host = await storage.authenticate_host(pg_db, token)
    assert host is not None
    with pytest.raises(storage.ToolNotGranted):
        await storage.resolve_host_credentials(pg_db, host, "pi")


async def test_expired_values_are_reported_but_not_served(pg_db: AsyncSession) -> None:
    token = await storage.add_host(pg_db, "agent-work")
    await storage.set_tool_grant(pg_db, "agent-work", "claude-code", granted=True)
    with pytest.raises(storage.RemoteHostError):
        await storage.store_tool_credential(pg_db, "claude-code", "oauth-token", SECRET,
                                            expires_at=datetime.now(UTC) - timedelta(days=1))
    await storage.store_tool_credential(pg_db, "claude-code", "oauth-token", SECRET,
                                        expires_at=datetime.now(UTC) + timedelta(days=365))
    stored = (await pg_db.execute(select(Credential))).scalar_one()
    from app.storage.credentials import encrypt_value

    stored.value_encrypted = encrypt_value(
        '{"schema_version": 1, "value": "old", "expires_at": "2020-01-01T00:00:00+00:00"}'
    )
    await pg_db.commit()
    states = {(s.row.tool_slug, s.row.name): s for s in await storage.tool_credential_states(pg_db)}
    assert states[("claude-code", "oauth-token")].expired is True
    host = await storage.authenticate_host(pg_db, token)
    assert host is not None
    with pytest.raises(storage.RemoteHostMissing):
        await storage.resolve_host_credentials(pg_db, host, "claude-code")


async def test_tool_map_rows_validate_delivery_and_remove_stored_values(pg_db: AsyncSession) -> None:
    row = storage.ToolMapRow(tool_slug="dummy", name="key", command="dummy-tool", config_dir="~/.dummy",
                             env_var="DUMMY_KEY", auth_file=None, rotates=False, description="")
    await storage.add_tool_row(pg_db, row)
    for bad in (
        {"env_var": None, "auth_file": None},
        {"env_var": "DUMMY_KEY", "auth_file": "auth.json"},
        {"env_var": None, "auth_file": "../escape.json"},
        {"config_dir": "/etc"},
    ):
        with pytest.raises(storage.RemoteHostError):
            await storage.add_tool_row(pg_db, storage.ToolMapRow(**{**vars(row), "name": "other", **bad}))
    await storage.store_tool_credential(pg_db, "dummy", "key", SECRET)
    await storage.delete_tool_row(pg_db, "dummy", "key")
    assert (await pg_db.execute(select(Credential))).first() is None
    assert await storage.list_tool_map(pg_db, "dummy") == []


@pytest_asyncio.fixture
async def client(pg_db: AsyncSession) -> AsyncGenerator[httpx.AsyncClient]:
    from app.db import get_db
    from app.main import app

    async def session() -> AsyncGenerator[AsyncSession]:
        yield pg_db

    app.dependency_overrides[get_db] = session
    transport = httpx.ASGITransport(app=app, client=("10.0.0.9", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
        yield http


async def test_fetch_endpoint_is_host_scoped_uncached_and_never_logged(
    pg_db: AsyncSession, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.middleware import access_control

    def no_request_log(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("host credential requests must not be request-logged")

    monkeypatch.setattr(access_control, "handle_identified_request", no_request_log)
    monkeypatch.setattr(access_control, "handle_auth_bypass", no_request_log)
    monkeypatch.setattr(access_control, "schedule_ui_request_log", no_request_log)
    caplog.set_level(logging.DEBUG)

    token = await storage.add_host(pg_db, "agent-work")
    other = await storage.add_host(pg_db, "other-host")
    await storage.set_tool_grant(pg_db, "agent-work", "claude-code", granted=True)
    await storage.store_tool_credential(pg_db, "claude-code", "oauth-token", SECRET)

    assert (await client.get("/api/host-credentials/claude-code")).status_code == 401
    bad = await client.get("/api/host-credentials/claude-code", headers={"Authorization": "Bearer ahh_nope"})
    assert bad.status_code == 401
    denied = await client.get("/api/host-credentials/claude-code", headers={"Authorization": f"Bearer {other}"})
    assert denied.status_code == 403

    response = await client.get("/api/host-credentials/claude-code", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["credentials"] == [{
        "name": "oauth-token", "config_dir": "~/.claude", "env_var": "CLAUDE_CODE_OAUTH_TOKEN",
        "auth_file": None, "value": SECRET,
    }]

    states = await client.get("/api/host-credentials/tools", headers={"Authorization": f"Bearer {token}"})
    assert states.status_code == 200 and SECRET not in states.text
    assert states.json()["granted_tools"] == ["claude-code"]

    await storage.revoke_host(pg_db, "agent-work")
    gone = await client.get("/api/host-credentials/claude-code", headers={"Authorization": f"Bearer {token}"})
    assert gone.status_code == 401
    assert SECRET not in caplog.text and token not in caplog.text


async def test_push_needs_a_grant_and_a_non_rotating_row(pg_db: AsyncSession, client: httpx.AsyncClient) -> None:
    token = await storage.add_host(pg_db, "agent-work")
    auth = {"Authorization": f"Bearer {token}"}
    body = {"value": SECRET}
    assert (await client.put("/api/host-credentials/claude-code/oauth-token", json=body, headers=auth)).status_code == 403
    await storage.set_tool_grant(pg_db, "agent-work", "claude-code", granted=True)
    await storage.set_tool_grant(pg_db, "agent-work", "codex", granted=True)
    assert (await client.put("/api/host-credentials/codex/login", json=body, headers=auth)).status_code == 400
    saved = await client.put("/api/host-credentials/claude-code/oauth-token", json=body, headers=auth)
    assert saved.status_code == 200 and SECRET not in saved.text and saved.json()["stored"] is True


async def test_owner_api_issues_a_token_once_and_lists_no_secrets(
    pg_db: AsyncSession, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import access_identity

    monkeypatch.setattr(access_identity, "_is_local_address", lambda value: True)
    owner = {"X-Agent-Hub-Internal": os.environ["INTERNAL_SERVICE_SECRET"]}
    created = await client.post("/api/remote-hosts", json={"name": "agent-work"}, headers=owner)
    assert created.status_code == 201
    token = created.json()["token"]
    assert (await client.put("/api/remote-hosts/agent-work/tools/claude-code", headers=owner)).json()[
        "granted_tools"
    ] == ["claude-code"]
    listed = await client.get("/api/remote-hosts", headers=owner)
    assert token not in listed.text and storage.hash_token(token) not in listed.text
    tool_map = await client.get("/api/remote-tools", headers=owner)
    assert {row["tool_slug"] for row in tool_map.json()["credentials"]} >= {"claude-code", "pi", "codex", "agy"}
    assert (await client.delete("/api/remote-hosts/agent-work", headers=owner)).status_code == 204
    assert await storage.authenticate_host(pg_db, token) is None


def test_st_hosts_add_writes_the_token_to_a_private_file_and_never_prints_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_hub_st.agents import app
    from typer.testing import CliRunner

    from app.cli import remote_hosts as cli

    async def fake_action(action: str, arguments: dict[str, Any]) -> Any:
        assert (action, arguments) == ("add", {"name": "agent-work"})
        return "ahh_" + "t" * 43

    monkeypatch.setattr(cli, "_database_action", fake_action)
    out = tmp_path / "token"
    result = CliRunner().invoke(app, ["hosts", "add", "agent-work", "--token-out", str(out)])
    assert result.exit_code == 0, result.output
    assert "ahh_" not in result.output
    assert out.read_text().strip() == "ahh_" + "t" * 43
    assert out.stat().st_mode & 0o777 == 0o600
    again = CliRunner().invoke(app, ["hosts", "add", "agent-work", "--token-out", str(out)])
    assert again.exit_code == 1 and "ahh_" not in again.output


def test_st_hosts_credential_set_reads_only_a_private_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_hub_st.agents import app
    from typer.testing import CliRunner

    from app.cli import remote_hosts as cli

    seen: list[dict[str, Any]] = []

    async def fake_action(action: str, arguments: dict[str, Any]) -> Any:
        seen.append(arguments)
        return {"tool": arguments["tool_slug"], "name": arguments["name"], "stored": True, "expires_at": None}

    monkeypatch.setattr(cli, "_database_action", fake_action)
    value = tmp_path / "value"
    value.write_text(SECRET)
    value.chmod(0o644)
    args = ["hosts", "credential-set", "st", "summitflow-agent-token", "--input", str(value)]
    refused = CliRunner().invoke(app, args)
    assert refused.exit_code == 1 and not seen
    value.chmod(0o600)
    saved = CliRunner().invoke(app, args)
    assert saved.exit_code == 0, saved.output
    assert SECRET not in saved.output and seen[0]["value"] == SECRET
