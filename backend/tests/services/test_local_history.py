"""Local harness history: the deletion guard never removes an un-imported or recently used transcript."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.services import local_history
from app.services.local_history import (
    HistoryUnit,
    ImportCursor,
    claude_units,
    codex_thread_id,
    keep_reason,
    prune_local_history,
    reclaim_sqlite,
    subagent_session_id,
)

NOW = time.time()
DAY = 86400
THREAD = "019a0000-1111-7222-8333-444455556666"


def _write(path: Path, content: bytes, *, age_days: float = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
    return path


def _cursor(path: Path, *, offset: int | None = None, events_held: bool = True, labels=(), children=()) -> ImportCursor:
    data = path.read_bytes()
    offset = len(data) if offset is None else offset
    stat = path.stat()
    return ImportCursor(
        session_id=path.stem, device=stat.st_dev, inode=stat.st_ino, byte_offset=offset,
        tail_digest=hashlib.sha256(data[max(0, offset - 128):offset]).hexdigest(),
        events_held=events_held, labels=tuple(labels), children=tuple(children),
    )


DEFAULT_EXCLUDES = Settings.model_fields["local_history_exclude_globs"].default.split(",")


def _reason(unit: HistoryUnit, cursors: dict[str, ImportCursor], *, open_files=frozenset()):
    return keep_reason(
        unit, cursors, now=NOW, retention_days=7, exclude_globs=DEFAULT_EXCLUDES, open_files=set(open_files),
    )


@pytest.mark.unit
def test_idle_fully_imported_transcript_may_be_deleted(tmp_path: Path) -> None:
    transcript = _write(tmp_path / "pi" / "--repo--" / "s.jsonl", b'{"type":"message"}\n')
    assert _reason(HistoryUnit("pi", transcript), {str(transcript): _cursor(transcript)}) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("recent", "recent"),
        ("unregistered", "not_in_agent_hub"),
        ("behind", "not_fully_imported"),
        ("replaced", "not_fully_imported"),
        ("events_purged", "events_not_held"),
        ("open", "open"),
        ("excluded_path", "excluded"),
        ("excluded_cwd", "excluded"),
        ("excluded_case", "excluded"),
        ("rewritten_same_size", "not_fully_imported"),
        ("lossy", "parse_issues"),
        ("duplicate", "duplicate_sessions"),
    ],
)
def test_guard_keeps_transcripts_agent_hub_cannot_stand_in_for(tmp_path: Path, case: str, expected: str) -> None:
    folder = "-srv-workspaces-projects-neri" if case == "excluded_path" else "-srv-repo"
    transcript = _write(tmp_path / folder / "s.jsonl", b'{"a":1}\n{"b":2}\n', age_days=1 if case == "recent" else 10)
    cursor = _cursor(
        transcript,
        offset=8 if case == "behind" else None,
        events_held=case != "events_purged",
        labels={"excluded_cwd": ("/srv/scratch/neri-lab",), "excluded_case": ("/srv/scratch/Neri-Lab",)}.get(
            case, ("/srv/repo",),
        ),
    )
    if case in {"lossy", "duplicate"}:
        cursor = replace(cursor, lossy=case == "lossy", duplicate=case == "duplicate")
    if case == "rewritten_same_size":
        with transcript.open("r+b") as handle:  # same inode and size, different bytes
            handle.write(b'{"c":3}\n')
        os.utime(transcript, (NOW - 10 * DAY, NOW - 10 * DAY))
    if case == "replaced":
        copy = transcript.with_suffix(".tmp")
        shutil.copy2(transcript, copy)
        copy.replace(transcript)  # same bytes, new inode: not the file Agent Hub read
    cursors = {} if case == "unregistered" else {str(transcript): cursor}
    open_files = {os.path.realpath(transcript)} if case == "open" else set()
    assert _reason(HistoryUnit("pi", transcript), cursors, open_files=open_files) == expected


@pytest.mark.unit
def test_claude_session_waits_for_every_transcript_in_its_folder(tmp_path: Path) -> None:
    transcript = _write(tmp_path / "-srv-repo" / "parent.jsonl", b'{"type":"user"}\n')
    agent = _write(tmp_path / "-srv-repo" / "parent" / "subagents" / "agent-a1.jsonl", b'{"type":"assistant"}\n')
    workflow = agent.parent / "workflows" / "wf_1"
    nested = _write(workflow / "agent-a2.jsonl", b'{"type":"assistant"}\n')
    journal = _write(workflow / "journal.jsonl", b'{"step":1}\n')
    _write(agent.with_name("agent-a1.meta.json"), b"{}")
    for folder in (workflow, workflow.parent, agent.parent, agent.parent.parent):
        os.utime(folder, (NOW - 10 * DAY, NOW - 10 * DAY))
    (unit,) = claude_units(tmp_path)
    assert sorted(unit.dependents) == sorted([agent, nested, journal])
    cursors = {str(transcript): _cursor(transcript), str(agent): _cursor(agent), str(nested): _cursor(nested)}
    assert _reason(unit, cursors) == "not_in_agent_hub"  # the workflow journal is not in Agent Hub

    journal.unlink()
    os.utime(workflow, (NOW - 10 * DAY, NOW - 10 * DAY))
    unit.dependents.remove(journal)
    assert _reason(unit, cursors) is None

    os.utime(nested, (NOW - 3600, NOW - 3600))  # a workflow agent is still in use
    assert _reason(unit, cursors) == "recent"


@pytest.mark.unit
def test_memory_folders_are_not_session_units(tmp_path: Path) -> None:
    _write(tmp_path / "-srv-repo" / "memory" / "MEMORY.md", b"keep")
    _write(tmp_path / "-srv-repo" / "s.jsonl", b"{}\n")
    assert [unit.transcript.name for unit in claude_units(tmp_path)] == ["s.jsonl"]


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd CLI not installed")
@pytest.mark.parametrize(("imported_lines", "expected"), [(2, None), (1, "not_fully_imported")])
def test_compressed_codex_rollout_is_checked_against_its_content(
    tmp_path: Path, imported_lines: int, expected: str | None,
) -> None:
    plain = _write(tmp_path / "2026" / "10" / "01" / f"rollout-2026-10-01T00-00-00-{THREAD}.jsonl", b'{"a":1}\n{"b":2}\n')
    cursor = _cursor(plain, offset=len(b'{"a":1}\n{"b":2}\n'.split(b"\n", imported_lines)[0]) + 1 if imported_lines == 1 else None)
    subprocess.run(["zstd", "-q", "--rm", str(plain)], check=True)
    compressed = plain.with_name(plain.name + ".zst")
    os.utime(compressed, (NOW - 10 * DAY, NOW - 10 * DAY))
    assert _reason(HistoryUnit("codex", compressed), {str(plain): cursor}) == expected
    assert codex_thread_id(compressed) == THREAD


@pytest.mark.unit
def test_codex_parent_waits_for_spawned_threads_its_delete_would_take(tmp_path: Path) -> None:
    parent = _write(tmp_path / f"rollout-a-{THREAD}.jsonl", b"{}\n")
    child = _write(tmp_path / "rollout-b-019a0000-1111-7222-8333-777777777777.jsonl", b"{}\n{}\n")
    cursors = {str(parent): _cursor(parent, children=(str(child),))}
    assert _reason(HistoryUnit("codex", parent), cursors) == "not_in_agent_hub"
    cursors[str(child)] = _cursor(child, offset=3)
    assert _reason(HistoryUnit("codex", parent), cursors) == "not_fully_imported"
    cursors[str(child)] = _cursor(child)
    assert _reason(HistoryUnit("codex", parent), cursors) is None


@pytest.mark.unit
def test_codex_threads_from_spawn_edges_become_dependents(tmp_path: Path) -> None:
    child_id, grandchild_id = "019a0000-1111-7222-8333-777777777777", "019a0000-1111-7222-8333-888888888888"
    with sqlite3.connect(tmp_path / "state_5.sqlite") as db:
        db.execute("CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT, status TEXT)")
        db.executemany("INSERT INTO thread_spawn_edges VALUES (?, ?, 'closed')", [(THREAD, child_id), (child_id, grandchild_id)])
    units = [
        HistoryUnit("codex", tmp_path / f"rollout-a-{THREAD}.jsonl", codex_home=tmp_path),
        HistoryUnit("codex", tmp_path / f"rollout-b-{child_id}.jsonl.zst", codex_home=tmp_path),
        HistoryUnit("codex", tmp_path / f"rollout-c-{grandchild_id}.jsonl", codex_home=tmp_path),
    ]
    local_history._attach_codex_threads(units)
    assert sorted(units[0].dependents) == sorted([units[1].transcript, units[2].transcript])
    assert units[2].dependents == []


@pytest.mark.unit
def test_subagent_session_ids_are_stable_and_fit_the_id_column() -> None:
    first = subagent_session_id("parent", "subagents/agent-a1.jsonl")
    assert first == subagent_session_id("parent", "subagents/agent-a1.jsonl")
    assert first != subagent_session_id("parent", "subagents/workflows/wf_1/agent-a1.jsonl")
    assert first != subagent_session_id("other", "subagents/agent-a1.jsonl")
    assert len(first) == 36


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    roots = SimpleNamespace(claude=tmp_path / "claude", codex=tmp_path / "codex" / "sessions", pi=tmp_path / "pi")
    monkeypatch.setattr(local_history, "claude_project_roots", lambda: [roots.claude])
    monkeypatch.setattr(local_history, "codex_session_roots", lambda: [roots.codex])
    monkeypatch.setattr(local_history, "pi_session_roots", lambda: [roots.pi])
    monkeypatch.setattr(local_history.settings, "local_history_retention_days", 7)
    return roots


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
async def test_prune_removes_only_guarded_units_and_counts_the_rest(stores: SimpleNamespace, dry_run: bool) -> None:
    done = _write(stores.pi / "--repo--" / "done.jsonl", b"{}\n")
    fresh = _write(stores.pi / "--repo--" / "fresh.jsonl", b"{}\n", age_days=0)
    unknown = _write(stores.claude / "-srv-repo" / "unknown.jsonl", b"{}\n")
    cursors = {str(done): _cursor(done), str(fresh): _cursor(fresh)}
    removed: list[Path] = []
    with patch.object(local_history, "load_cursors", AsyncMock(return_value=cursors)):
        result = await prune_local_history(
            MagicMock(), dry_run=dry_run, now=NOW, open_files=set(),
            remove=lambda unit, _bin: removed.append(unit.transcript),
        )
    assert result["pi"] == {"deleted": 1, "freed_bytes": 3, "kept": {"recent": 1}}
    assert result["claude_code"]["kept"] == {"not_in_agent_hub": 1}
    assert removed == ([] if dry_run else [done])
    assert unknown.exists() and fresh.exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prune_is_off_at_zero_retention_days(stores: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_history.settings, "local_history_retention_days", 0)
    load = AsyncMock()
    with patch.object(local_history, "load_cursors", load):
        assert await prune_local_history(MagicMock(), now=NOW, open_files=set()) == {}
    load.assert_not_awaited()


@pytest.mark.unit
def test_remove_deletes_claude_sidecar_with_transcript(tmp_path: Path) -> None:
    transcript = _write(tmp_path / "s.jsonl", b"{}\n")
    sidecar = _write(tmp_path / "s" / "tool-results" / "r.txt", b"x").parent.parent
    unit = HistoryUnit("claude_code", transcript, sidecar)
    assert unit.paths() == [sidecar, transcript]  # an interrupted delete leaves the transcript to find again
    local_history._remove(unit, "codex")
    assert not transcript.exists() and not sidecar.exists()


@pytest.mark.unit
def test_remove_deletes_a_codex_thread_through_codex(tmp_path: Path) -> None:
    rollout = _write(tmp_path / f"rollout-x-{THREAD}.jsonl.zst", b"z")
    def fake_codex(*args, **kwargs):
        rollout.unlink()
        return SimpleNamespace(returncode=0)

    with patch.object(local_history, "run_process", side_effect=fake_codex) as run:
        local_history._remove(HistoryUnit("codex", rollout, codex_home=tmp_path), "/opt/codex")
    assert run.call_args is not None
    assert run.call_args.args[0] == ["/opt/codex", "delete", "--force", THREAD]
    assert run.call_args.kwargs["env"]["CODEX_HOME"] == str(tmp_path)
    rollout = _write(tmp_path / f"rollout-x-{THREAD}.jsonl.zst", b"z")
    with (
        patch.object(local_history, "run_process", return_value=SimpleNamespace(returncode=0)),
        pytest.raises(RuntimeError, match="left"),
    ):
        local_history._remove(HistoryUnit("codex", rollout), "codex")
    with (
        patch.object(local_history, "run_process", return_value=SimpleNamespace(returncode=1, stderr="busy", stdout="")),
        pytest.raises(RuntimeError, match="busy"),
    ):
        local_history._remove(HistoryUnit("codex", rollout), "codex")


@pytest.mark.unit
def test_reclaim_returns_free_pages_only_for_incremental_databases(tmp_path: Path) -> None:
    def build(name: str, auto_vacuum: str) -> Path:
        path = tmp_path / name
        db = sqlite3.connect(path)
        db.execute(f"PRAGMA auto_vacuum={auto_vacuum}")
        db.execute("PRAGMA journal_mode=wal")
        db.execute("CREATE TABLE t (v BLOB)")
        db.executemany("INSERT INTO t VALUES (?)", [(b"x" * 4000,)] * 500)
        db.commit()
        db.execute("DELETE FROM t")
        db.commit()
        db.close()
        return path

    incremental, plain = build("thread_history.sqlite", "INCREMENTAL"), build("other.sqlite", "NONE")
    assert reclaim_sqlite(incremental) > 1_000_000
    assert sqlite3.connect(incremental).execute("PRAGMA freelist_count").fetchone()[0] == 0
    assert reclaim_sqlite(plain) == 0
    assert sqlite3.connect(plain).execute("PRAGMA freelist_count").fetchone()[0] > 0


def _session(session_id: str, transcript: Path, *, checkpoint: str | None = None, parent: str | None = None):
    metadata = {"transcript_path": str(transcript), "cwd": "/srv/repo", "repo_root": "/srv/repo"}
    if checkpoint is not None:
        metadata["transcript_ingestion"] = {"checkpoint": checkpoint}
    return SimpleNamespace(
        id=session_id, project_id="agent-hub", provider="anthropic", model="claude-opus-5-5",
        current_branch="main", parent_session_id=parent, provider_metadata=metadata, status="completed",
    )


def _checkpoint(path: Path, offset: int) -> str:
    import json

    stat = path.stat()
    data = path.read_bytes()
    return json.dumps({
        "line_offset": 1, "byte_offset": offset, "device": stat.st_dev, "inode": stat.st_ino,
        "tail_digest": hashlib.sha256(data[max(0, offset - 128):offset]).hexdigest(),
        "turn": 1, "sequence": 0, "saw_content": True,
    })


@pytest.mark.unit
@pytest.mark.asyncio
async def test_catch_up_imports_missed_turns_and_records_subagents(
    stores: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_history.settings, "local_history_catch_up_idle_minutes", 60)
    transcript = _write(stores.claude / "-srv-repo" / "p.jsonl", b'{"type":"user"}\n{"type":"assistant"}\n')
    agent = _write(stores.claude / "-srv-repo" / "p" / "subagents" / "agent-a1.jsonl", b'{"type":"user"}\n')
    _write(agent.with_name("agent-a1.meta.json"), b'{"agentType":"Explore","description":"look"}')
    live_agent = _write(stores.claude / "-srv-repo" / "p" / "subagents" / "agent-a2.jsonl", b"{}\n", age_days=0)
    parent = _session("p", transcript, checkpoint=_checkpoint(transcript, 16))
    child = _session(subagent_session_id("p", "subagents/agent-a1.jsonl"), agent, parent="p")
    child.provider_metadata.pop("transcript_ingestion", None)
    sessions = {"p": parent}
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: [("p", str(transcript))]))
    db.get = AsyncMock(side_effect=lambda _model, key: sessions.get(key))
    ingest = AsyncMock(return_value=SimpleNamespace(events_appended=2))
    upsert = AsyncMock(return_value=(child, None))
    close = AsyncMock()
    with (
        patch.object(local_history, "ingest_transcript_events", ingest),
        patch.object(local_history, "upsert_session", upsert),
        patch.object(local_history, "close_session_if_active", close),
    ):
        counts = await local_history.catch_up_claude_code(db, now=NOW)

    assert counts == {"caught_up": 1, "subagents_recorded": 1, "events_appended": 4}
    assert [call.args[1] for call in ingest.await_args_list] == ["p", child.id]
    assert upsert.await_args is not None
    request = upsert.await_args.args[1]
    assert (request.parent_session_id, request.project_id, request.session_id) == ("p", "agent-hub", child.id)
    assert request.provider_metadata["native_subagent_type"] == "Explore"
    assert request.provider_metadata["transcript_path"] == str(agent)
    assert str(live_agent) not in str(upsert.await_args_list)
    close.assert_awaited_once_with(db, child)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_catch_up_never_reimports_a_replaced_transcript(stores: SimpleNamespace) -> None:
    transcript = _write(stores.claude / "-srv-repo" / "p.jsonl", b'{"type":"user"}\n')
    checkpoint = _checkpoint(transcript, 8)
    copy = transcript.with_suffix(".tmp")
    shutil.copy2(transcript, copy)
    copy.replace(transcript)
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=lambda: [("p", str(transcript))]))
    db.get = AsyncMock(return_value=_session("p", transcript, checkpoint=checkpoint))
    ingest = AsyncMock()
    with patch.object(local_history, "ingest_transcript_events", ingest):
        counts = await local_history.catch_up_claude_code(db, now=NOW)
    assert counts == {"source_changed": 1}
    ingest.assert_not_awaited()
