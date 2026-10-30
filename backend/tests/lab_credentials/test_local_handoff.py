"""Synthetic-only local boundary tests: no live config, DB or target contact."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from app.cli import lab_credentials as local
from app.storage.lab_credentials import (
    LabCredentialError,
    ResolvedLabCredential,
    enroll_lab_credential,
    list_lab_credential_refs,
)

REF = "secret://lab/example-local/viewer"


def private_json(tmp_path, value):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


@pytest.mark.asyncio
async def test_enrollment_checks_expiry_after_waiting_for_lock(monkeypatch):
    from app.storage import lab_credentials as storage

    now = datetime(2026, 1, 1, tzinfo=UTC)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now + timedelta(seconds=2)

    db = MagicMock()
    @asynccontextmanager
    async def transaction():
        yield

    db.begin.side_effect = transaction
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    monkeypatch.setattr(storage, "datetime", Clock)
    with pytest.raises(LabCredentialError, match="expired"):
        await enroll_lab_credential(db, REF, {"password": "synthetic-fixture"}, kind="temporary",
                                    expires_at=now + timedelta(seconds=1))
    assert db.execute.await_count == 2
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_enrollment_locks_before_check_and_never_replaces():
    events = []
    db = MagicMock()

    @asynccontextmanager
    async def transaction():
        events.append("begin")
        yield
        events.append("commit")

    async def execute(statement):
        events.append("lock" if "LOCK TABLE" in str(statement) else "lookup")
        return MagicMock(all=lambda: [])

    db.begin.side_effect = transaction
    db.execute = AsyncMock(side_effect=execute)
    db.add.side_effect = lambda row: events.append("insert")
    db.flush = AsyncMock(side_effect=lambda: events.append("flush"))
    assert await enroll_lab_credential(db, REF, {"password": "synthetic-fixture"}, kind="synthetic") == REF
    assert events == ["begin", "lock", "lookup", "insert", "flush", "commit"]
    assert "value_encrypted" not in str(db.execute.call_args_list[1].args[0])


@pytest.mark.parametrize("existing", [[(1,)], [(1,), (2,)]])
@pytest.mark.asyncio
async def test_occupied_reference_rolls_back_without_insert(existing):
    db = MagicMock()
    rolled_back = []

    @asynccontextmanager
    async def transaction():
        try:
            yield
        except LabCredentialError:
            rolled_back.append(True)
            raise

    db.begin.side_effect = transaction
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: existing))
    with pytest.raises(LabCredentialError):
        await enroll_lab_credential(db, REF, {"password": "synthetic-fixture"}, kind="synthetic")
    assert rolled_back == [True]
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_metadata_listing_selects_no_ciphertext(synthetic_settings, monkeypatch):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: [("_lab_example-local", "viewer")]))
    monkeypatch.setattr(synthetic_settings, "decrypt_value", MagicMock(side_effect=AssertionError("no decryption")))
    assert await list_lab_credential_refs(db, "example-local") == [REF]
    assert {column.name for column in db.execute.call_args.args[0].selected_columns} == {"provider", "credential_type"}


@pytest.mark.asyncio
async def test_metadata_listing_without_target_names_every_lab_target(synthetic_settings, monkeypatch):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: [("_lab_example-local", "viewer"), ("_lab_other", "default")]))
    monkeypatch.setattr(synthetic_settings, "decrypt_value", MagicMock(side_effect=AssertionError("no decryption")))
    assert await list_lab_credential_refs(db, None) == [REF, "secret://lab/other/default"]
    assert {column.name for column in db.execute.call_args.args[0].selected_columns} == {"provider", "credential_type"}


@pytest.mark.parametrize("rows", [
    [("_lab_example-local", "viewer"), ("_lab_example-local", "viewer")],
    [("_lab_other", "viewer")], [("_lab_example-local", "bad/actor")],
])
@pytest.mark.asyncio
async def test_metadata_listing_rejects_duplicates_and_scope(rows):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: rows))
    with pytest.raises(LabCredentialError):
        await list_lab_credential_refs(db, "example-local")


def test_input_file_checks_descriptor_permissions_owner_type_and_symlink(tmp_path, monkeypatch):
    path = private_json(tmp_path, {"password": "synthetic-fixture"})
    assert local._read_document(path, protected=True) == {"password": "synthetic-fixture"}
    path.chmod(0o640)
    with pytest.raises(LabCredentialError):
        local._read_document(path, protected=True)
    path.chmod(0o600)
    monkeypatch.setattr(local.os, "geteuid", lambda: path.stat().st_uid + 1)
    with pytest.raises(LabCredentialError):
        local._read_document(path, protected=True)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        local._read_document(link, protected=True)
    with pytest.raises(LabCredentialError):
        local._read_document(Path("/dev/null"), protected=True)


def test_piped_stdin_and_private_regular_stdin(tmp_path, monkeypatch):
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b'{"username":"synthetic-fixture"}')
    os.close(write_fd)
    original_dup = os.dup
    monkeypatch.setattr(local.os, "dup", lambda fd: original_dup(read_fd))
    try:
        assert local._read_document(None, protected=True) == {"username": "synthetic-fixture"}
        os.fchmod(read_fd, 0o640)
        with pytest.raises(LabCredentialError):
            local._read_document(None, protected=True)
    finally:
        os.close(read_fd)
    monkeypatch.setattr(local.os, "dup", original_dup)
    path = private_json(tmp_path, {})
    with path.open("rb") as stream:
        monkeypatch.setattr(local.os, "dup", lambda fd: original_dup(stream.fileno()))
        assert local._read_document(None, protected=True) == {}
        path.chmod(0o644)
        with pytest.raises(LabCredentialError):
            local._read_document(None, protected=True)


@pytest.mark.parametrize("data", [b'{"password":"a","password":"b"}', b"invalid-json", b"x" * (local.MAX_DOCUMENT_BYTES + 1)])
def test_ambiguous_invalid_or_oversized_input_fails_before_database(tmp_path, monkeypatch, data):
    path = tmp_path / "input"
    path.write_bytes(data)
    path.chmod(0o600)
    action = AsyncMock()
    monkeypatch.setattr(local, "_database_action", action)
    with pytest.raises(LabCredentialError):
        local.run_lab_operation("enroll", target="example-local", actor="viewer", kind="synthetic", input_file=path)
    action.assert_not_called()


def test_enrollment_only_returns_reference_and_parses_expiry(tmp_path, monkeypatch):
    path = private_json(tmp_path, {"password": "synthetic-fixture"})
    action = AsyncMock(return_value=REF)
    monkeypatch.setattr(local, "_database_action", action)
    result = local.run_lab_operation("enroll", target="example-local", actor="viewer", kind="temporary",
                                      expires_at="2099-01-01T00:00:00+00:00", input_file=path)
    assert result == {"reference": REF}
    assert action.call_args.kwargs["expires_at"].year == 2099


def test_database_session_is_closed_before_handoff(tmp_path, monkeypatch):
    events = []
    db_module = ModuleType("app.db")

    @asynccontextmanager
    async def session():
        events.append("open")
        yield MagicMock()
        events.append("closed")

    monkeypatch.setattr(db_module, "async_session", session, raising=False)
    monkeypatch.setitem(sys.modules, "app.db", db_module)
    monkeypatch.setattr(local, "resolve_lab_credentials", AsyncMock(return_value=[]))
    def handoff(*args):
        assert events == ["open", "closed"]
        return 7
    monkeypatch.setattr(local, "_handoff", handoff)
    request = private_json(tmp_path, [{"reference": REF, "fields": ["password"]}])
    assert local.run_lab_operation("run", target="example-local", request_file=request, command=["/bin/true"]) == {"exit_code": 7}


@pytest.mark.parametrize("selection", [[], {}, [{"reference": REF, "fields": "password"}], [{"reference": REF, "fields": [1]}]])
def test_bad_selection_never_reaches_database(tmp_path, monkeypatch, selection):
    request = private_json(tmp_path, selection)
    action = AsyncMock()
    monkeypatch.setattr(local, "_database_action", action)
    with pytest.raises(LabCredentialError):
        local.run_lab_operation("run", target="example-local", request_file=request, command=["/bin/true"])
    action.assert_not_called()


def test_resolution_failure_never_launches_child(tmp_path, monkeypatch):
    request = private_json(tmp_path, [{"reference": REF, "fields": ["password"]}])
    monkeypatch.setattr(local, "_database_action", AsyncMock(side_effect=LabCredentialError("unavailable")))
    child = MagicMock()
    monkeypatch.setattr(local, "_handoff", child)
    with pytest.raises(LabCredentialError):
        local.run_lab_operation("run", target="example-local", request_file=request, command=["/bin/true"])
    child.assert_not_called()


def test_relative_child_rejected_before_resolution(tmp_path, monkeypatch):
    request = private_json(tmp_path, [{"reference": REF, "fields": ["password"]}])
    action = AsyncMock()
    monkeypatch.setattr(local, "_database_action", action)
    with pytest.raises(LabCredentialError):
        local.run_lab_operation("run", target="example-local", request_file=request, command=["relative-child"])
    action.assert_not_called()


def test_oversized_handoff_never_starts_child(monkeypatch):
    child = MagicMock()
    monkeypatch.setattr(local.subprocess, "run", child)
    with pytest.raises(LabCredentialError):
        local._handoff("example-local", [ResolvedLabCredential(REF, {"password": "x" * local.MAX_DOCUMENT_BYTES})], ["/bin/true"])
    child.assert_not_called()


def test_queue_failure_closes_descriptors_without_launch(monkeypatch):
    reader, writer = MagicMock(), MagicMock()
    writer.sendall.side_effect = BlockingIOError("full")
    monkeypatch.setattr(local.socket, "socketpair", lambda: (reader, writer))
    child = MagicMock()
    monkeypatch.setattr(local.subprocess, "run", child)
    with pytest.raises(BlockingIOError):
        local._handoff("example-local", [ResolvedLabCredential(REF, {"password": "synthetic-fixture"})], ["/bin/true"])
    child.assert_not_called()
    reader.close.assert_called_once()
    writer.close.assert_called_once()


def test_real_child_receives_descriptor_only_and_output_is_suppressed(monkeypatch, capfd):
    monkeypatch.setenv("HOST_TEST_CREDENTIAL", "synthetic-host-fixture")
    # The child validates the contract internally and emits no credential data.
    script = """
import json, os, sys
fd = int(os.environ['AGENT_HUB_LAB_CREDENTIAL_FD'])
with os.fdopen(fd) as stream:
    data = json.load(stream)
assert data['schema_version'] == 1
assert data['target'] == 'example-local'
assert list(data['credentials'][0]['values']) == ['password']
assert data['credentials'][0]['values']['password']
assert 'HOST_TEST_CREDENTIAL' not in os.environ
assert not any(key in os.environ for key in ('HOME', 'AGENT_HUB_ENCRYPTION_KEY', 'SSH_AUTH_SOCK'))
assert sys.stdin.read() == ''
print('child-output-must-be-suppressed')
print('child-error-must-be-suppressed', file=sys.stderr)
"""
    assert local._handoff("example-local", [ResolvedLabCredential(REF, {"password": os.urandom(16).hex()})],
                          [sys.executable, "-I", "-c", script]) == 0
    captured = capfd.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("failure", [False, True])
def test_handoff_argv_env_and_descriptor_cleanup(monkeypatch, failure):
    seen = []
    def child(command, **kwargs):
        assert command == ["/bin/true"]
        assert set(kwargs["env"]) == {"PATH", local.HANDOFF_FD_ENV}
        fd, = kwargs["pass_fds"]
        seen.append(fd)
        assert json.loads(os.read(fd, local.MAX_DOCUMENT_BYTES))["credentials"][0]["values"] == {"username": "synthetic-fixture"}
        with pytest.raises(OSError):
            os.write(fd, b"no")
        assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        if failure:
            raise OSError("synthetic child error")
        return subprocess.CompletedProcess(command, -15)
    monkeypatch.setattr(local.subprocess, "run", child)
    if failure:
        with pytest.raises(OSError):
            local._handoff("example-local", [ResolvedLabCredential(REF, {"username": "synthetic-fixture"})], ["/bin/true"])
    else:
        assert local._handoff("example-local", [ResolvedLabCredential(REF, {"username": "synthetic-fixture"})], ["/bin/true"]) == 143
    with pytest.raises(OSError):
        os.fstat(seen[0])


def test_cli_registers_without_backend_import_and_preserves_child_arguments(monkeypatch):
    from agent_hub_st import lab_credentials as extension
    from agent_hub_st.agents import app
    from st_sdk.runtime import describe_app

    assert "credentials run" in describe_app(app, "agents")["help"]
    action = MagicMock(return_value={"exit_code": 7})
    monkeypatch.setattr(extension, "_run_local", action)
    result = CliRunner().invoke(app, ["credentials", "run", "--target", "example-local", "--request", "requests.json", "--", "/bin/true", "--child-option", "value"])
    assert result.exit_code == 7
    assert action.call_args.kwargs["command"] == ["/bin/true", "--child-option", "value"]


def test_cli_sanitizes_all_errors_and_never_prints_exception_contents(monkeypatch):
    from agent_hub_st import lab_credentials as extension
    from agent_hub_st.agents import app

    monkeypatch.setattr(extension, "_run_local", MagicMock(side_effect=RuntimeError("synthetic-private-error")))
    result = CliRunner().invoke(app, ["credentials", "refs", "--target", "example-local"])
    assert result.exit_code == 1
    assert "synthetic-private-error" not in result.output
    assert "Traceback" not in result.output


def test_cli_backend_binding_uses_its_own_source(monkeypatch):
    from agent_hub_st import lab_credentials as extension

    action = MagicMock(return_value={"references": []})
    monkeypatch.setattr(local, "run_lab_operation", action)
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert extension._run_local("refs", target="example-local") == {"references": []}
    assert Path(sys.path[0]) == Path(extension.__file__).resolve().parents[3] / "backend"
    action.assert_called_once_with("refs", target="example-local")
