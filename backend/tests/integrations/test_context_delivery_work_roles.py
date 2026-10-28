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


@pytest.mark.asyncio
async def test_retirement_forwards_only_exact_owner_to_canonical_cli(client, monkeypatch):
    surface = "pi"
    run = AsyncMock(return_value=(0, b"", b""))
    globals_ = client["_main"].__globals__
    monkeypatch.setitem(globals_, "_run", run)
    monkeypatch.setitem(globals_, "_canonical_cli", AsyncMock(return_value="canonical-cli"))
    args = client["_parser"]().parse_args([f"retire-{surface}", "--surface", surface,
                                           "--aico-session", "aico-widget-12345678"])
    assert await client["_main"](args) == 0
    run.assert_awaited_once_with("canonical-cli", f"retire-{surface}", "--aico-session", "aico-widget-12345678")


async def _delivery_tags(client, monkeypatch, command, surface, hook=None, coordinator=False):
    globals_ = client["_resolve_metadata"].__globals__
    monkeypatch.setitem(globals_, "_git_value", AsyncMock(return_value=None))
    monkeypatch.setitem(globals_, "_tether_coordinator", lambda _widget: coordinator)
    args = client["_parser"]().parse_args([command, "--surface", surface, "--cwd", "/fixture"])
    metadata = await client["_resolve_metadata"](args, hook or {})
    return metadata["consumer_tags"], client["_delivery_command"]("canonical-cli", metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["pi", "codex", "claude_code"])
@pytest.mark.parametrize("command", ["deliver", "hook"])
async def test_root_delivery_carries_declared_work_role_tag(client, monkeypatch, surface, command):
    hook = {"hook_event_name": "SessionStart", "session_id": SID} if command == "hook" else None
    tags, argv = await _delivery_tags(client, monkeypatch, command, surface, hook)
    assert tags == ["work-role:implementation"]
    assert argv[argv.index("--consumer-tag") + 1] == "work-role:implementation"


@pytest.mark.asyncio
async def test_work_role_tag_is_independent_of_coordinator_membership(client, monkeypatch):
    tags, _argv = await _delivery_tags(client, monkeypatch, "deliver", "pi", coordinator=True)
    assert tags == ["aico-coordinator", "work-role:implementation"]


@pytest.mark.asyncio
@pytest.mark.parametrize("hook", [
    {"hook_event_name": "SubagentStart", "session_id": SID},
    {"hook_event_name": "SessionStart", "session_id": SID, "agent_id": "child"},
    {"hook_event_name": "SessionStart", "session_id": SID, "agent_type": "explore"},
    {"hook_event_name": "SessionStart", "session_id": SID, "parent_session_id": "parent"},
])
async def test_child_delivery_never_inherits_parent_work_role(client, monkeypatch, hook):
    tags, argv = await _delivery_tags(client, monkeypatch, "hook", "claude_code", hook)
    assert tags == []
    assert "--consumer-tag" not in argv


@pytest.mark.asyncio
async def test_unproven_role_and_bind_add_no_delivery_tag(client, monkeypatch):
    tags, _argv = await _delivery_tags(client, monkeypatch, "bind", "codex",
                                       {"hook_event_name": "SessionStart", "session_id": SID})
    assert tags == []
    monkeypatch.delenv("ST_WORK_ROLE_SOURCE")
    tags, _argv = await _delivery_tags(client, monkeypatch, "deliver", "pi")
    assert tags == []
