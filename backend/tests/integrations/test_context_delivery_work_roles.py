"""Launch declarations follow exact native identity and never child hooks."""

import json
import runpy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

CLIENT = Path(__file__).resolve().parents[3] / "integrations/context-delivery/bin/agent-hub-context-client"
SID = "00000000-0000-4000-8000-000000000001"
ROLE = {"id": "implementation", "source": "tether:root:fixture", "display_name": "Builder"}


@pytest.fixture
def client(monkeypatch):
    loaded = runpy.run_path(str(CLIENT))
    monkeypatch.setenv("ST_WORK_ROLE", ROLE["id"])
    monkeypatch.setenv("ST_WORK_ROLE_SOURCE", ROLE["source"])
    monkeypatch.setenv("ST_WORK_ROLE_DISPLAY_NAME", ROLE["display_name"])
    return loaded


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["codex", "claude_code"])
async def test_root_bind_uses_native_uuid_without_artifact_or_widget_identity(client, monkeypatch, surface):
    run = AsyncMock(return_value=(0, b"", b""))
    globals_ = client["_bind_native_work_role"].__globals__
    monkeypatch.setitem(globals_, "_run", run)
    monkeypatch.setitem(globals_, "_canonical_cli", AsyncMock(return_value="canonical-cli"))
    monkeypatch.setitem(globals_, "_resolve_metadata", AsyncMock(return_value={
        "cwd": "/fixture", "project": "fixture", "session": "widget-correlation", "model": "native/model"}))
    args = client["_parser"]().parse_args(["bind", "--surface", surface])
    await client["_bind_native_work_role"](args, {"session_id": SID, "hook_event_name": "SessionStart"})
    assert run.await_args is not None
    argv = list(run.await_args.args)
    assert argv[:2] == ["canonical-cli", "bind-native-work-role"]
    assert argv[argv.index("--session") + 1] == SID
    assert json.loads(argv[argv.index("--work-role-json") + 1]) == ROLE
    assert "widget-correlation" not in argv


@pytest.mark.asyncio
@pytest.mark.parametrize("hook", [
    {"hook_event_name": "SubagentStart", "session_id": SID},
    {"hook_event_name": "SessionStart", "session_id": SID, "agent_id": "child"},
    {"hook_event_name": "SessionStart", "session_id": SID, "parent_session_id": "parent"},
    {"hook_event_name": "SessionStart"},
])
async def test_child_and_unproven_identity_never_declare(client, monkeypatch, hook):
    run = AsyncMock()
    monkeypatch.setitem(client["_bind_native_work_role"].__globals__, "_run", run)
    args = client["_parser"]().parse_args(["bind", "--surface", "codex"])
    await client["_bind_native_work_role"](args, hook)
    run.assert_not_awaited()


def test_missing_provenance_stays_unknown(client, monkeypatch):
    monkeypatch.delenv("ST_WORK_ROLE_SOURCE")
    assert client["_launch_work_role"]() is None


@pytest.mark.asyncio
async def test_pi_sync_forwards_launch_declaration_on_existing_sync_seam(client, monkeypatch):
    run = AsyncMock(return_value=(0, b"{}", b""))
    globals_ = client["_main"].__globals__
    monkeypatch.setitem(globals_, "_run", run)
    monkeypatch.setitem(globals_, "_canonical_cli", AsyncMock(return_value="canonical-cli"))
    monkeypatch.setitem(globals_, "_resolve_metadata", AsyncMock(return_value={
        "cwd": "/fixture", "session": SID, "provider": "openai", "model": "native"}))
    args = client["_parser"]().parse_args(["sync-pi", "--surface", "pi", "--session", SID,
                                           "--transcript", "/fixture/transcript.jsonl"])
    assert await client["_main"](args) == 0
    assert run.await_args is not None
    argv = list(run.await_args.args)
    assert argv[:2] == ["canonical-cli", "sync-pi"]
    assert argv[argv.index("--session") + 1] == SID
    assert json.loads(argv[argv.index("--work-role-json") + 1]) == ROLE
