"""Session records from remote agent hosts: transcript copies, host scoping, and the host-token routes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException, Request

from app.services import remote_host_sessions as hosts
from app.services.remote_host_sessions import (
    HostSessionRefused,
    HostSessionSync,
    HostWorkRoleBinding,
    TranscriptOffsetMismatch,
    append_transcript,
    transcript_file,
    transcript_size,
)
from app.storage.remote_hosts import HostIdentity
from app.utils import native_homes

SID = "00000000-0000-4000-8000-000000000001"
PARENT = "00000000-0000-4000-8000-000000000002"
CLAUDE_PATH = f"-srv-workspaces-projects-agent-hub/{SID}.jsonl"
CODEX_PATH = f"2026/10/30/rollout-2026-10-30T10-00-00-{SID}.jsonl"
TOKEN = "host-token-" + "y" * 20
CWD = "/srv/workspaces/projects/agent-hub"


@pytest.fixture(autouse=True)
def host_homes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "host-homes"
    monkeypatch.setenv("AGENT_HUB_HOST_HOMES", str(root))
    return root


def test_copies_live_in_the_host_home_at_the_hosts_own_layout(host_homes: Path) -> None:
    assert transcript_file("agent-work", "claude_code", SID, CLAUDE_PATH) == (
        host_homes / "agent-work/.claude/projects" / CLAUDE_PATH)
    assert transcript_file("agent-work", "codex", SID, CODEX_PATH) == host_homes / "agent-work/.codex/sessions" / CODEX_PATH
    assert transcript_file("agent-work", "pi", SID, f"--srv--/2026_{SID}.jsonl").parts[-4:-1] == (
        "agent", "sessions", "--srv--")


@pytest.mark.parametrize(("surface", "session", "path"), [
    ("shell", SID, CLAUDE_PATH),
    ("claude_code", "not-a-uuid", CLAUDE_PATH),
    ("claude_code", SID, f"../{SID}.jsonl"),
    ("claude_code", SID, f"/etc/{SID}.jsonl"),
    ("claude_code", SID, f"a//{SID}.jsonl"),
    ("claude_code", SID, f"a/{SID}.json"),
    ("claude_code", SID, f"a/{PARENT}.jsonl"),  # another session's transcript
    ("codex", SID, f"1/2/3/4/{SID}.jsonl"),
    ("claude_code", SID, f"a b/{SID}.jsonl"),
])
def test_paths_that_are_not_this_sessions_transcript_are_refused(surface: str, session: str, path: str) -> None:
    with pytest.raises(HostSessionRefused):
        transcript_file("agent-work", surface, session, path)


def test_append_continues_at_the_copys_end_and_refuses_gaps_and_overflow(host_homes: Path) -> None:
    assert transcript_size("agent-work", "claude_code", SID, CLAUDE_PATH) == 0
    assert append_transcript("agent-work", "claude_code", SID, CLAUDE_PATH, 0, b'{"a":1}\n', max_bytes=64) == 8
    assert append_transcript("agent-work", "claude_code", SID, CLAUDE_PATH, 8, b'{"b"', max_bytes=64) == 12
    with pytest.raises(TranscriptOffsetMismatch) as mismatch:
        append_transcript("agent-work", "claude_code", SID, CLAUDE_PATH, 4, b"x", max_bytes=64)
    assert mismatch.value.size == 12
    with pytest.raises(HostSessionRefused) as overflow:
        append_transcript("agent-work", "claude_code", SID, CLAUDE_PATH, 12, b"x" * 60, max_bytes=64)
    assert overflow.value.status == 413
    copy = transcript_file("agent-work", "claude_code", SID, CLAUDE_PATH)
    assert copy.read_bytes() == b'{"a":1}\n{"b"'
    assert copy.stat().st_mode & 0o777 == 0o600


def test_a_link_out_of_the_host_home_is_refused(host_homes: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (host_homes / "agent-work/.claude").mkdir(parents=True)
    (host_homes / "agent-work/.claude/projects").symlink_to(outside)
    with pytest.raises(HostSessionRefused):
        append_transcript("agent-work", "claude_code", SID, CLAUDE_PATH, 0, b"x", max_bytes=64)
    assert not any(outside.rglob("*.jsonl"))


def test_each_host_home_is_a_native_home(host_homes: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_HUB_NATIVE_HOMES", raising=False)
    (host_homes / "agent-work").mkdir(parents=True)
    assert host_homes / "agent-work" in native_homes.native_homes()
    assert host_homes / "agent-work/.claude/projects" in native_homes.claude_project_roots()
    assert host_homes / "agent-work/.pi/agent/sessions" in native_homes.pi_session_roots()
    monkeypatch.setenv("AGENT_HUB_NATIVE_HOMES", "/elsewhere")
    assert native_homes.native_homes() == [Path("/elsewhere")]


# Sync: the local paths' services, called with the host's copy and its name --------------


def _db(existing: Any = None) -> AsyncMock:
    db = AsyncMock()
    db.execute.return_value.scalar_one_or_none = MagicMock(return_value=existing)
    return db


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    session = SimpleNamespace(id=SID, status="active")
    calls = SimpleNamespace(
        project=AsyncMock(return_value="agent-hub"),
        upsert=AsyncMock(return_value=(session, None)),
        ingest=AsyncMock(return_value=SimpleNamespace(events_appended=3, events_skipped=1)),
        finalize=AsyncMock(),
        close=AsyncMock(return_value=("completed", "Session closed successfully")),
        pi=AsyncMock(return_value={"session_id": SID, "events_appended": 2}),
        bind=AsyncMock(),
    )
    monkeypatch.setattr(hosts, "_resolve_canonical_project_id", calls.project)
    monkeypatch.setattr(hosts, "upsert_session", calls.upsert)
    monkeypatch.setattr(hosts, "ingest_transcript_events", calls.ingest)
    monkeypatch.setattr(hosts, "finalize_session", calls.finalize)
    monkeypatch.setattr(hosts, "close_session_if_active", calls.close)
    monkeypatch.setattr(hosts, "sync_pi_session", calls.pi)
    monkeypatch.setattr(hosts, "bind_native_work_role", calls.bind)
    return calls


def _copy(surface: str, path: str, rows: list[dict[str, Any]], session: str = SID) -> Path:
    data = "".join(json.dumps(row) + "\n" for row in rows).encode()
    append_transcript("agent-work", surface, session, path, 0, data, max_bytes=1 << 20)
    return transcript_file("agent-work", surface, session, path)


async def test_claude_stop_hook_sync_records_upserts_ingests_finalizes_and_closes(services: SimpleNamespace) -> None:
    copy = _copy("claude_code", CLAUDE_PATH, [{"type": "user", "sessionId": SID}])
    body = HostSessionSync(surface="claude_code", session_id=SID, path=CLAUDE_PATH, cwd=CWD, project="agent-hub",
                           provider="anthropic", model="claude-opus-5-5", branch="main", repo_root=CWD,
                           git_context="abc fix", aico_session_id="aico-widget-1234abcd", finalize=True)

    result = await hosts.sync_host_session(_db(), "agent-work", body)

    upsert = services.upsert.await_args.args[1]
    assert (upsert.session_id, upsert.session_type, upsert.request_source, upsert.model) == (
        SID, "claude_code", "hook", "claude-opus-5-5")
    assert upsert.provider_metadata == {
        "host": "agent-work", "remote_host": "agent-work", "harness": "claude_code", "transcript_path": str(copy),
        "repo_root": CWD, "aico_session_id": "aico-widget-1234abcd"}
    ingest = services.ingest.await_args.args[2]
    assert (ingest.provider, ingest.transcript_path) == ("claude_code", str(copy))
    assert services.finalize.await_args.args[1].git_context == "abc fix"
    services.close.assert_awaited_once()
    assert result == {"session_id": SID, "events_appended": 3, "events_skipped": 1, "status": "completed"}


async def test_codex_sync_reads_lineage_from_the_copy_and_needs_the_parent_on_this_host(
    services: SimpleNamespace,
) -> None:
    header = {"type": "session_meta", "payload": {"id": SID, "session_id": PARENT, "cwd": CWD,
              "source": {"subagent": {"thread_spawn": {"parent_thread_id": PARENT, "agent_path": "/root/w"}}}}}
    copy = _copy("codex", CODEX_PATH, [header])
    body = HostSessionSync(surface="codex", session_id=SID, path=CODEX_PATH, cwd=CWD, aico_session_id="aico-widget-1",
                           aico_project_id="agent-hub")
    parent = SimpleNamespace(provider_metadata={"remote_host": "agent-work"})
    db = _db()
    db.execute.return_value.scalar_one_or_none = MagicMock(side_effect=[None, parent])

    await hosts.sync_host_session(db, "agent-work", body)

    upsert = services.upsert.await_args.args[1]
    assert (upsert.provider, upsert.session_type, upsert.parent_session_id) == ("codex", "agent", PARENT)
    assert upsert.request_source == "codex-transcript-sync"
    meta = upsert.provider_metadata
    assert (meta["remote_host"], meta["transcript_path"], meta["native_session_id"]) == ("agent-work", str(copy), PARENT)
    assert meta["external_identity"]["agent_path"] == "/root/w"
    assert meta["external_identity"]["project_mapping_state"] == "matched"
    assert services.ingest.await_args.args[2].provider == "codex"
    services.close.assert_not_awaited()

    db.execute.return_value.scalar_one_or_none = MagicMock(side_effect=[None, SimpleNamespace(provider_metadata={})])
    with pytest.raises(HostSessionRefused) as refused:
        await hosts.sync_host_session(db, "agent-work", body)
    assert refused.value.status == 403  # the parent is a workstation session


async def test_pi_sync_goes_through_pi_sync_with_the_host_recorded(services: SimpleNamespace) -> None:
    path = f"--srv-workspaces-projects-agent-hub--/2026-10-30_{SID}.jsonl"
    copy = _copy("pi", path, [{"type": "session", "id": SID}])
    body = HostSessionSync(surface="pi", session_id=SID, path=path, cwd=CWD, provider="opencode-go",
                           model="deepseek-v4.1-flash", phase="working", aico_session_id="aico-widget-1234abcd",
                           work_role={"id": "implementation", "source": "tether:root:fixture"})

    await hosts.sync_host_session(_db(), "agent-work", body)

    kwargs = services.pi.await_args.kwargs
    assert kwargs["transcript"] == str(copy) and kwargs["phase"] == "working"
    assert kwargs["extra_metadata"] == {"host": "agent-work", "remote_host": "agent-work"}
    assert kwargs["work_role"] == {"id": "implementation", "source": "tether:root:fixture"}
    with pytest.raises(HostSessionRefused):
        await hosts.sync_host_session(_db(), "agent-work", body.model_copy(update={"model": None}))


@pytest.mark.parametrize("owner", [None, "other-host"])
async def test_a_host_never_writes_a_session_it_did_not_record(services: SimpleNamespace, owner: str | None) -> None:
    _copy("claude_code", CLAUDE_PATH, [{"type": "user"}])
    existing = SimpleNamespace(provider_metadata={"remote_host": owner} if owner else {"host": "agent-work"})
    body = HostSessionSync(surface="claude_code", session_id=SID, path=CLAUDE_PATH, cwd=CWD)
    with pytest.raises(HostSessionRefused) as refused:
        await hosts.sync_host_session(_db(existing), "agent-work", body)
    assert refused.value.status == 403
    role = HostWorkRoleBinding(surface="codex", session_id=SID, cwd=CWD,
                               work_role={"id": "implementation", "source": "tether:root:fixture"})
    with pytest.raises(HostSessionRefused):
        await hosts.bind_host_work_role(_db(existing), "agent-work", role)
    services.upsert.assert_not_awaited()
    services.bind.assert_not_awaited()


async def test_sync_before_the_transcript_arrives_and_outside_projects_are_refused(services: SimpleNamespace) -> None:
    body = HostSessionSync(surface="claude_code", session_id=SID, path=CLAUDE_PATH, cwd="/tmp/aico-blank-slate")
    with pytest.raises(HostSessionRefused) as missing:
        await hosts.sync_host_session(_db(), "agent-work", body)
    assert missing.value.code == "transcript_missing"
    _copy("claude_code", CLAUDE_PATH, [{"type": "user"}])
    services.project.return_value = None
    with pytest.raises(HostSessionRefused) as outside:
        await hosts.sync_host_session(_db(), "agent-work", body)
    assert outside.value.code == "unregistered_cwd"


async def test_work_role_binding_records_the_host(services: SimpleNamespace) -> None:
    role = HostWorkRoleBinding(surface="claude_code", session_id=SID, cwd=CWD, model="claude-opus-5-5",
                               work_role={"id": "coordinator", "source": "tether:root:fixture"})
    await hosts.bind_host_work_role(_db(), "agent-work", role)
    kwargs = services.bind.await_args.kwargs
    assert (kwargs["surface"], kwargs["project_id"], kwargs["work_role"]["id"]) == ("claude_code", "agent-hub", "coordinator")
    assert kwargs["extra_metadata"] == {"host": "agent-work", "remote_host": "agent-work"}


# The routes, through the app -----------------------------------------------------------


async def fake_require_host(request: Request) -> HostIdentity:
    if request.headers.get("Authorization") != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="Unknown or revoked host token")
    return HostIdentity("agent-work", ())


async def no_db() -> Any:
    yield None


@pytest.fixture
async def http(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.api.remote_hosts import require_host
    from app.config import settings
    from app.db import get_db
    from app.main import app

    monkeypatch.setattr(settings, "host_transcript_chunk_max_bytes", 1024)
    app.dependency_overrides[require_host] = fake_require_host
    app.dependency_overrides[get_db] = no_db
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            yield client
    finally:
        app.dependency_overrides.pop(require_host, None)
        app.dependency_overrides.pop(get_db, None)


AUTH = {"Authorization": f"Bearer {TOKEN}"}
URL = f"/api/host-sessions/transcripts/claude_code/{SID}"


async def test_routes_need_the_host_token_and_are_never_request_logged(http: httpx.AsyncClient) -> None:
    from app.middleware.access_control_paths import is_path_exempt

    assert is_path_exempt("/api/host-sessions/sync")
    for method, path in (("GET", URL), ("POST", URL), ("POST", "/api/host-sessions/sync"),
                         ("POST", "/api/host-sessions/work-role"), ("POST", "/api/host-sessions/retire-pi")):
        response = await http.request(method, path, params={"path": CLAUDE_PATH, "offset": 0}, content=b"{}")
        assert response.status_code == 401, path


async def test_transcript_routes_append_raw_bytes_and_answer_offsets_and_limits(http: httpx.AsyncClient) -> None:
    params = {"path": CLAUDE_PATH}
    assert (await http.get(URL, params=params, headers=AUTH)).json() == {"size": 0}
    sent = await http.post(URL, params={**params, "offset": 0}, content=b'{"a":1}\n', headers=AUTH)
    assert sent.json() == {"size": 8}
    stale = await http.post(URL, params={**params, "offset": 0}, content=b"x", headers=AUTH)
    assert stale.status_code == 409 and stale.json()["details"] == [{"size": 8}]
    too_big = await http.post(URL, params={**params, "offset": 8}, content=b"x" * 2048, headers=AUTH)
    assert too_big.status_code == 413
    bad = await http.get(URL, params={"path": f"../{SID}.jsonl"}, headers=AUTH)
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_path"
    assert (await http.get(URL, params=params, headers=AUTH)).json() == {"size": 8}


async def test_sync_route_maps_a_foreign_session_to_403(http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import host_sessions

    async def foreign(*_args: Any) -> None:
        raise HostSessionRefused("session_not_on_host", "This session was not recorded from this host.", 403)

    monkeypatch.setattr(host_sessions, "sync_host_session", foreign)
    body = {"surface": "claude_code", "session_id": SID, "path": CLAUDE_PATH, "cwd": CWD}
    refused = await http.post("/api/host-sessions/sync", json=body, headers=AUTH)
    assert refused.status_code == 403 and refused.json()["error"] == "session_not_on_host"
    invalid = await http.post("/api/host-sessions/sync", json={**body, "surface": "shell"}, headers=AUTH)
    assert invalid.status_code == 422


async def test_retire_route_is_scoped_to_the_host(http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    retire = AsyncMock(return_value={"aico_session_id": "aico-widget-1234abcd", "closed_session_ids": [],
                                     "unavailable_session_ids": []})
    monkeypatch.setattr(hosts, "retire_pi_sessions", retire)
    response = await http.post("/api/host-sessions/retire-pi", json={"aico_session_id": "aico-widget-1234abcd"},
                               headers=AUTH)
    assert response.status_code == 200
    assert retire.await_args is not None and retire.await_args.kwargs == {"remote_host": "agent-work"}


def test_copies_stay_private(host_homes: Path) -> None:
    append_transcript("agent-work", "pi", SID, f"d/{SID}.jsonl", 0, b"x", max_bytes=8)
    for directory in (host_homes / "agent-work/.pi", host_homes / "agent-work/.pi/agent/sessions/d"):
        assert os.stat(directory).st_mode & 0o077 == 0
