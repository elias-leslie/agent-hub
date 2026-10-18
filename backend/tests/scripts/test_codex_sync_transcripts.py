from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

codex_sync_transcripts = importlib.import_module("codex_sync_transcripts")


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )


def test_has_live_codex_process_detects_wrapper_or_binary(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_dir = proc_root / "123"
    proc_dir.mkdir(parents=True)
    (proc_dir / "cmdline").write_bytes(b"bash\0/home/demo/bin/codex\0--yolo\0")

    assert codex_sync_transcripts.has_live_codex_process(proc_root)


def test_has_live_codex_process_ignores_sync_script(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_dir = proc_root / "123"
    proc_dir.mkdir(parents=True)
    (proc_dir / "cmdline").write_bytes(b"python\0scripts/codex-session-sync.py\0")

    assert not codex_sync_transcripts.has_live_codex_process(proc_root)


def test_iter_open_transcript_paths_returns_open_codex_jsonl(tmp_path: Path) -> None:
    transcripts_root = tmp_path / "sessions"
    transcript = transcripts_root / "2026" / "04" / "rollout.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}", encoding="utf-8")

    proc_root = tmp_path / "proc"
    fd_dir = proc_root / "123" / "fd"
    fd_dir.mkdir(parents=True)
    (proc_root / "123" / "cmdline").write_bytes(b"/usr/local/bin/codex\0")
    (fd_dir / "26").symlink_to(transcript)

    assert codex_sync_transcripts.iter_open_transcript_paths(
        proc_root=proc_root,
        transcripts_root=transcripts_root,
    ) == {transcript.resolve()}


def test_read_transcript_info_keeps_first_child_session_meta(tmp_path: Path) -> None:
    transcript = tmp_path / "child.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "child-session",
                    "cwd": "/srv/workspaces/projects/a-loom",
                    "source": {
                        "subagent": {
                            "thread_spawn": {
                                "parent_thread_id": "parent-session",
                                "agent_nickname": "Leibniz",
                                "agent_path": "/root/aico_session_federation",
                            }
                        }
                    },
                },
            },
            {
                "type": "session_meta",
                "payload": {
                    "id": "parent-session",
                    "cwd": "/wrong/parent/cwd",
                    "source": "cli",
                },
            },
            {"type": "turn_context", "payload": {"model": "gpt-5.4"}},
        ],
    )

    info = codex_sync_transcripts.read_transcript_info(transcript)

    assert info is not None
    assert info.session_id == "child-session"
    assert info.cwd == Path("/srv/workspaces/projects/a-loom")
    assert info.parent_session_id == "parent-session"
    assert info.agent_nickname == "Leibniz"
    assert info.agent_path == "/root/aico_session_federation"


def test_read_transcript_info_root_has_no_parent_identity(tmp_path: Path) -> None:
    transcript = tmp_path / "root.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "root-session",
                    "cwd": "/srv/workspaces/projects/a-loom",
                    "source": "cli",
                },
            },
            {"type": "turn_context", "payload": {"model": "gpt-5.4"}},
        ],
    )

    info = codex_sync_transcripts.read_transcript_info(transcript)

    assert info is not None
    assert info.session_id == "root-session"
    assert info.parent_session_id is None
    assert info.agent_nickname is None
    assert info.agent_path is None


def _meta(session_id="root", *, parent=None, native_session=None, agent_path=None):
    payload = {
        "id": session_id, "session_id": native_session or session_id,
        "cwd": "/srv/workspaces/projects/a-loom", "timestamp": "2026-09-30T10:00:00Z",
        "source": "cli",
    }
    if parent:
        payload.update({"parent_thread_id": parent, "agent_path": agent_path or "/root/child"})
        payload["source"] = {"subagent": {"thread_spawn": {
            "parent_thread_id": parent, "agent_path": agent_path or "/root/child",
        }}}
    return {"type": "session_meta", "payload": payload}


def _context(turn, model, timestamp="2026-09-30T10:01:00Z"):
    return {"type": "turn_context", "timestamp": timestamp,
            "payload": {"turn_id": turn, "model": model, "effort": "high"}}


def _started(turn, timestamp="2026-09-30T10:01:00Z"):
    return {"type": "event_msg", "timestamp": timestamp,
            "payload": {"type": "task_started", "turn_id": turn}}


def test_incremental_identity_scan_leaves_all_model_semantics_to_agent_hub(tmp_path):
    transcript = tmp_path / "root.jsonl"
    records = [_meta(), _context("t1", "requested-model")]
    _write_jsonl(transcript, records)
    first = codex_sync_transcripts.read_transcript_info(transcript)
    unchanged = codex_sync_transcripts.read_transcript_info(transcript, scan_state=first.identity_scan)
    assert unchanged.identity_scan == first.identity_scan
    records += [_started("t2"), _context("t2", "different-model"), {
        "type": "event_msg", "payload": {"type": "token_usage_record", "thread_id": "root", "turn_id": "t2", "model": "served-model"},
    }]
    _write_jsonl(transcript, records)
    latest = codex_sync_transcripts.read_transcript_info(transcript, scan_state=first.identity_scan)
    assert latest.model == "unknown"
    assert latest.identity_scan["source_generation"] == first.identity_scan["source_generation"]
    assert latest.identity_scan["offset"] > first.identity_scan["offset"]
    assert not any(key in latest.identity_scan for key in ("evidence", "active_turn", "requested_model", "observed_model"))


def test_child_identity_survives_inherited_and_local_model_evidence(tmp_path):
    transcript = tmp_path / "child.jsonl"
    records = [_meta("child", parent="root", native_session="root"), _meta(),
        _started("parent-turn", "2026-09-30T09:00:00Z"), _context("parent-turn", "parent-model")]
    _write_jsonl(transcript, records)
    parent_only = codex_sync_transcripts.read_transcript_info(transcript)
    records += [_started("child-turn"), _context("child-turn", "child-model"), {
        "type": "event_msg", "payload": {"type": "token_usage_record", "thread_id": "child", "session_id": "root", "turn_id": "child-turn", "model": "served-model"},
    }]
    _write_jsonl(transcript, records)
    child = codex_sync_transcripts.read_transcript_info(transcript, scan_state=parent_only.identity_scan)
    assert child.session_id == "child" and child.parent_session_id == "root"
    assert child.native_session_id == "root" and child.model == "unknown"


@pytest.mark.parametrize("wrong", [{"thread_id": "other"}, {"session_id": "other"}, {"turn_id": "old"}])
def test_observed_model_rejects_wrong_attribution(tmp_path, wrong):
    payload = {"type": "token_usage_record", "thread_id": "root", "session_id": "root",
               "turn_id": "current", "model": "wrong-model"}
    payload.update(wrong)
    transcript = tmp_path / "root.jsonl"
    _write_jsonl(transcript, [_meta(), _context("current", "requested"), {"type": "event_msg", "payload": payload}])
    assert codex_sync_transcripts.read_transcript_info(transcript).model == "unknown"


@pytest.mark.parametrize("environment,caller,current", [
    ({"CODEX_SESSION_ID": "root", "CODEX_THREAD_ID": "stale"}, {"CODEX_SESSION_ID": "root"}, "root"),
    ({"CODEX_SESSION_ID": "root", "CODEX_THREAD_ID": "child"}, {"CODEX_SESSION_ID": "root", "CODEX_THREAD_ID": "child"}, "child"),
    ({"CODEX_SESSION_ID": "child", "CODEX_THREAD_ID": "root"}, {"CODEX_THREAD_ID": "child"}, "child"),
])
def test_resolver_validates_both_native_identity_layouts(tmp_path, environment, caller, current):
    root = tmp_path / "root.jsonl"
    child = tmp_path / "child.jsonl"
    _write_jsonl(root, [_meta()])
    _write_jsonl(child, [_meta("child", parent="root", native_session="root")])
    snapshot = codex_sync_transcripts.OpenTranscriptSnapshot(frozenset({root, child}), {}, frozenset())
    info = codex_sync_transcripts.resolve_current_transcript(environment, snapshot, caller)
    assert info.session_id == current
    assert info.parent_session_id == ("root" if current == "child" else None)
    assert info.agent_path == ("/root/child" if current == "child" else None)


@pytest.mark.parametrize("caller", [{}, {"CODEX_THREAD_ID": "unrelated"}, {"CODEX_THREAD_ID": "child", "CODEX_SESSION_ID": "other"}])
def test_resolver_rejects_unproven_or_conflicting_caller(tmp_path, caller):
    child = tmp_path / "child.jsonl"
    _write_jsonl(child, [_meta("child", parent="root", native_session="root")])
    snapshot = codex_sync_transcripts.OpenTranscriptSnapshot(frozenset({child}), {}, frozenset())
    with pytest.raises(ValueError):
        codex_sync_transcripts.resolve_current_transcript({"CODEX_THREAD_ID": "child", "CODEX_SESSION_ID": "root"}, snapshot, caller)


@pytest.mark.parametrize("key,value", [("parent_thread_id", "other"), ("agent_path", "/root/other"), ("session_id", "invalid identity")])
def test_resolver_rejects_contradictory_header(tmp_path, key, value):
    record = _meta("child", parent="root", native_session="root")
    record["payload"][key] = value
    child = tmp_path / "child.jsonl"
    _write_jsonl(child, [record])
    snapshot = codex_sync_transcripts.OpenTranscriptSnapshot(frozenset({child}), {}, frozenset())
    with pytest.raises(ValueError, match="Conflicting"):
        codex_sync_transcripts.resolve_current_transcript({"CODEX_THREAD_ID": "child"}, snapshot, {"CODEX_THREAD_ID": "child"})


def test_incremental_partial_record_retried_and_truncation_resets(tmp_path):
    transcript = tmp_path / "root.jsonl"
    _write_jsonl(transcript, [_meta(), _context("current", "requested")])
    first = codex_sync_transcripts.read_transcript_info(transcript)
    with transcript.open("ab") as handle:
        handle.write(b'{"type":"turn_context","payload":')
    partial = codex_sync_transcripts.read_transcript_info(transcript, scan_state=first.identity_scan)
    assert partial.identity_scan["offset"] == first.identity_scan["offset"]
    with transcript.open("ab") as handle:
        handle.write(b'{"turn_id":"next","model":"new"}}\n')
    complete = codex_sync_transcripts.read_transcript_info(transcript, scan_state=partial.identity_scan)
    assert complete.identity_scan["offset"] == transcript.stat().st_size
    assert complete.model == "unknown"
    _write_jsonl(transcript, [_meta("replacement")])
    replacement = codex_sync_transcripts.read_transcript_info(transcript, scan_state=complete.identity_scan)
    assert replacement.session_id == "replacement"
    assert replacement.model == "unknown"


def test_incremental_same_inode_larger_rewrite_revalidates_header(tmp_path):
    transcript = tmp_path / "root.jsonl"
    _write_jsonl(transcript, [_meta(), _context("current", "requested")])
    first = codex_sync_transcripts.read_transcript_info(transcript)
    _write_jsonl(transcript, [_meta("replacement"), _context("replacement-turn", "replacement-model"),
        {"type": "event_msg", "payload": {"type": "token_count", "padding": "x" * 200}}])
    assert transcript.stat().st_size > first.size
    replacement = codex_sync_transcripts.read_transcript_info(transcript, scan_state=first.identity_scan)
    assert replacement.session_id == "replacement"
    assert replacement.model == "unknown"
    assert replacement.identity_scan["source_generation"] != first.identity_scan["source_generation"]


@pytest.mark.parametrize("override", [False, True])
def test_caller_native_ancestry_rejects_intermediary_identity_override(tmp_path, monkeypatch, override):
    proc = tmp_path / "proc"
    for pid, parent, command, identity in [
        (10, 20, b"python\0st\0", "other" if override else "child"),
        (20, 30, b"bash\0-c\0st sessions bind\0", "child"),
        (30, 1, b"/usr/bin/codex\0", "root"),
    ]:
        entry = proc / str(pid)
        entry.mkdir(parents=True)
        (entry / "cmdline").write_bytes(command)
        (entry / "environ").write_bytes(f"CODEX_THREAD_ID={identity}\0CODEX_SESSION_ID=root\0PRIVATE_SECRET=excluded\0".encode())
        (entry / "status").write_text(f"PPid:\t{parent}\n")
    monkeypatch.setattr(codex_sync_transcripts.os, "getpid", lambda: 10)
    if override:
        with pytest.raises(ValueError, match="Contradictory"):
            codex_sync_transcripts._caller_native_identity(proc)
    else:
        assert codex_sync_transcripts._caller_native_identity(proc) == {"CODEX_THREAD_ID": "child", "CODEX_SESSION_ID": "root"}


@pytest.mark.parametrize(
    "payload",
    [
        {  # Codex guardian review child: top-level parent, no agent path.
            "id": "guardian-child",
            "session_id": "parent-session",
            "parent_thread_id": "parent-session",
            "source": {"subagent": {"other": "guardian"}},
            "thread_source": "guardian_review",
        },
        {  # Older thread_spawn header with a null agent path.
            "id": "spawned-child",
            "session_id": "spawned-child",
            "source": {"subagent": {"thread_spawn": {
                "parent_thread_id": "parent-session", "agent_path": None, "agent_nickname": "Meitner",
            }}},
        },
    ],
)
def test_pathless_child_is_a_valid_child_not_a_root(tmp_path: Path, payload: dict[str, object]) -> None:
    transcript = tmp_path / "child.jsonl"
    _write_jsonl(transcript, [{"type": "session_meta", "payload": {"cwd": "/srv/workspaces/projects/a-loom", **payload}}])

    info = codex_sync_transcripts.read_transcript_info(transcript)

    assert info is not None
    assert info.identity_error is None
    assert info.parent_session_id == "parent-session"
    assert info.agent_path is None
    assert codex_sync_transcripts.external_agent_path(info) is None


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"id": "self-child", "parent_thread_id": "self-child", "source": {"subagent": {"other": "guardian"}}},
         "contradictory native child provenance"),
        ({"id": "root-child", "parent_thread_id": "parent-session", "agent_path": "/root"},
         "contradictory native child provenance"),
    ],
)
def test_child_provenance_contradictions_are_still_rejected(
    tmp_path: Path, payload: dict[str, object], error: str,
) -> None:
    transcript = tmp_path / "child.jsonl"
    _write_jsonl(transcript, [{"type": "session_meta", "payload": {"cwd": "/tmp", **payload}}])

    info = codex_sync_transcripts.read_transcript_info(transcript)

    assert info is not None
    assert info.identity_error == error


def test_external_agent_path_defaults_only_roots_to_root() -> None:
    from types import SimpleNamespace

    assert codex_sync_transcripts.external_agent_path(SimpleNamespace(agent_path=None, parent_session_id=None)) == "/root"
    assert codex_sync_transcripts.external_agent_path(SimpleNamespace(agent_path="/root/x", parent_session_id="p")) == "/root/x"
    assert codex_sync_transcripts.external_agent_path(SimpleNamespace(agent_path=None, parent_session_id="p")) is None
