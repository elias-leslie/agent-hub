from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

agent = importlib.import_module("codex_sync_agent_tether")
NOW = 1_800_000_000.0


def _rollout(root: Path, name: str, thread: str, cwd: Path, mtime: float, parent: str | None = None) -> Path:
    path = root / "2026/10/19" / f"rollout-{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"id": thread, "cwd": str(cwd)}
    if parent:
        payload["source"] = {"subagent": {"thread_spawn": {"parent_thread_id": parent, "agent_nickname": "n"}}}
    path.write_text(json.dumps({"type": "session_meta", "payload": payload}) + "\n")
    os.utime(path, (mtime, mtime))
    return path.resolve()


def _widget(wid: str, root: Path, created: float = NOW - 3600, **kw) -> dict:
    return {"id": wid, "ownershipId": f"aico-widget-{wid}", "tool": "codex", "status": "running", "available": True,
            "projectId": "nightshift", "projectRoot": str(root), "createdAt": int(created * 1000), **kw}


def _discover(tmp_path: Path, items, **kw):
    sock = tmp_path / "control.sock"
    import socket as _s
    if not sock.exists():  # a socket file that nothing listens on is enough: list_fn is stubbed
        _s.socket(_s.AF_UNIX).bind(str(sock))
    return agent.discover_agent_transcripts(roots=[tmp_path / "agent"], sockets=[sock], now=NOW,
                                            list_fn=lambda _p: items, **kw)


def test_one_window_one_project_owns_its_newest_rollout(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    old = _rollout(tmp_path / "agent", "a", "11111111-1111", proj, NOW - 1800)
    cur = _rollout(tmp_path / "agent", "b", "22222222-2222", proj, NOW - 20)
    child = _rollout(tmp_path / "agent", "c", "33333333-3333", proj, NOW - 5, parent="22222222-2222")
    other = _rollout(tmp_path / "agent", "d", "44444444-4444", tmp_path / "elsewhere", NOW - 5)
    snap = _discover(tmp_path, [_widget("800973c7", proj)])
    assert snap.paths == {cur, child}
    assert old not in snap.paths and other not in snap.paths
    for path in (cur, child):
        o = snap.owners[path]
        assert (o.harness, o.aico_session_id, o.aico_widget_id, o.aico_project_id) == (
            "codex", "aico-widget-800973c7", "800973c7", "nightshift")
    assert not snap.ambiguous_paths


def test_two_windows_in_one_project_are_ambiguous_not_guessed(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    a = _rollout(tmp_path / "agent", "a", "11111111-1111", proj, NOW - 20)
    b = _rollout(tmp_path / "agent", "b", "22222222-2222", proj, NOW - 10)
    snap = _discover(tmp_path, [_widget("800973c7", proj), _widget("fe6b3868", proj)])
    assert snap.paths == {a, b} and snap.ambiguous_paths == {a, b} and not snap.owners


def test_nothing_is_open_without_a_running_window_or_before_it_existed(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    _rollout(tmp_path / "agent", "a", "11111111-1111", proj, NOW - 20)
    assert _discover(tmp_path, []).paths == frozenset()
    ended = _widget("800973c7", proj, status="ended")
    assert _discover(tmp_path, [ended]).paths == frozenset()
    assert _discover(tmp_path, [_widget("800973c7", proj, created=NOW)]).paths == frozenset()  # window newer than the file


def test_unanswering_tether_keeps_recently_written_rollouts_open_without_an_owner(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    fresh = _rollout(tmp_path / "agent", "a", "11111111-1111", proj, NOW - 60)
    stale = _rollout(tmp_path / "agent", "b", "22222222-2222", proj, NOW - 7200)
    warnings: list[str] = []
    snap = _discover(tmp_path, None, log_fn=warnings.append)
    assert snap.paths == {fresh} and stale not in snap.paths and not snap.owners and warnings


def test_no_socket_or_roots_means_no_claim(tmp_path: Path) -> None:
    assert agent.discover_agent_transcripts(roots=[tmp_path], sockets=[tmp_path / "none.sock"], now=NOW).paths == frozenset()


def test_proc_view_wins_when_both_know_a_path() -> None:
    t = importlib.import_module("codex_sync_transcripts")
    p = Path("/x/rollout.jsonl")
    mine = t.AicoProcessOwner("codex", "aico-widget-1", "1", "p")
    theirs = t.AicoProcessOwner("codex", "aico-widget-2", "2", "q")
    merged = agent.merge_snapshots(t.OpenTranscriptSnapshot(frozenset({p}), {p: mine}, frozenset()),
                                   t.OpenTranscriptSnapshot(frozenset({p}), {p: theirs}, frozenset({p})))
    assert merged.owners == {p: mine} and not merged.ambiguous_paths


def test_list_codex_sessions_over_a_unix_socket(tmp_path: Path) -> None:
    import socket
    import threading

    sock = tmp_path / "c.sock"
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(sock))
    srv.listen(1)

    def serve() -> None:
        conn, _ = srv.accept()
        conn.recv(4096)
        body = json.dumps({"items": [{"id": "800973c7"}, "junk"]}).encode()
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
        conn.close()

    t = threading.Thread(target=serve)
    t.start()
    assert agent.list_codex_sessions(sock) == [{"id": "800973c7"}]
    t.join()
    srv.close()
    assert agent.list_codex_sessions(tmp_path / "gone.sock") is None
