from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

codex_sync_state = importlib.import_module("codex_sync_state")


def _state_for(path: Path, *, status: str, mtime: float = 10.0, size: int = 200) -> dict[str, object]:
    return {
        "transcripts": {
            str(path): {
                "session_id": "sess-1",
                "mtime": mtime,
                "size": size,
                "status": status,
                "detail": "appended=0 skipped=0",
                "updated_at": "2026-04-16T00:00:00+00:00",
            }
        }
    }


@pytest.mark.parametrize("status", [403, 409])
def test_legacy_rejections_skip_timer_growth_heartbeat_and_close(status: int) -> None:
    path = Path("/tmp/rejected.jsonl")
    state = _state_for(path, status="error")
    transcripts = cast(dict[str, dict[str, object]], state["transcripts"])
    transcripts[str(path)]["detail"] = f"upsert status={status} rejected"
    assert not codex_sync_state.should_sync(path, 99, 999, state, force=False)
    assert not codex_sync_state.should_sync(path, 99, 999, state, force=False, close_session=True)
    assert not codex_sync_state.should_heartbeat(path, state)
    assert codex_sync_state.iter_nonterminal_paths(state) == []
    assert codex_sync_state.should_sync(path, 99, 999, state, force=True)


def test_should_sync_skips_unchanged_active_entry_without_close() -> None:
    path = Path("/tmp/transcript.jsonl")
    state = _state_for(path, status="active")

    assert not codex_sync_state.should_sync(path, 10.0, 200, state, force=False)


def test_should_sync_allows_close_for_unchanged_active_entry() -> None:
    path = Path("/tmp/transcript.jsonl")
    state = _state_for(path, status="active")

    assert codex_sync_state.should_sync(
        path,
        10.0,
        200,
        state,
        force=False,
        close_session=True,
    )


def test_should_sync_still_skips_terminal_entry_during_close() -> None:
    path = Path("/tmp/transcript.jsonl")
    state = _state_for(path, status="terminal")

    assert not codex_sync_state.should_sync(
        path,
        10.0,
        200,
        state,
        force=False,
        close_session=True,
    )


def test_should_heartbeat_is_independent_of_transcript_change() -> None:
    path = Path("/tmp/transcript.jsonl")
    now = datetime(2026, 7, 15, tzinfo=UTC)
    state = _state_for(path, status="active")
    transcripts = cast(dict[str, dict[str, object]], state["transcripts"])
    entry = transcripts[str(path)]
    entry["last_heartbeat_at"] = (now - timedelta(seconds=31)).isoformat()

    assert codex_sync_state.should_heartbeat(path, state, now=now)
    assert not codex_sync_state.should_sync(path, 10.0, 200, state, force=False)


def test_should_heartbeat_respects_bounded_interval() -> None:
    path = Path("/tmp/transcript.jsonl")
    now = datetime(2026, 7, 15, tzinfo=UTC)
    state = _state_for(path, status="active")
    transcripts = cast(dict[str, dict[str, object]], state["transcripts"])
    entry = transcripts[str(path)]
    entry["last_heartbeat_at"] = (now - timedelta(seconds=10)).isoformat()

    assert not codex_sync_state.should_heartbeat(path, state, now=now)


def test_update_state_entry_preserves_checkpoint_during_heartbeat_only_update() -> None:
    path = Path("/tmp/transcript.jsonl")
    state = _state_for(path, status="active")
    transcripts = cast(dict[str, dict[str, object]], state["transcripts"])
    entry = transcripts[str(path)]
    entry["checkpoint"] = "checkpoint-1"

    codex_sync_state.update_state_entry(
        state,
        path,
        "sess-1",
        10.0,
        200,
        "active",
        "heartbeat",
        heartbeat_at="2026-07-15T00:00:00+00:00",
    )

    updated = transcripts[str(path)]
    assert updated["checkpoint"] == "checkpoint-1"
    assert updated["last_heartbeat_at"] == "2026-07-15T00:00:00+00:00"


def test_update_state_entry_persists_project_binding_fingerprint() -> None:
    path = Path("/tmp/transcript.jsonl")
    state = _state_for(path, status="skipped")

    codex_sync_state.update_state_entry(
        state,
        path,
        "sess-1",
        10.0,
        200,
        "active",
        "synced",
        project_binding_fingerprint="binding-sha",
    )

    transcripts = cast(dict[str, dict[str, object]], state["transcripts"])
    assert transcripts[str(path)]["project_binding_fingerprint"] == "binding-sha"


def test_iter_nonterminal_paths_excludes_closed_and_skipped() -> None:
    active = Path("/tmp/active.jsonl")
    terminal = Path("/tmp/terminal.jsonl")
    skipped = Path("/tmp/skipped.jsonl")
    state = {
        "transcripts": {
            str(active): {"status": "active"},
            str(terminal): {"status": "terminal"},
            str(skipped): {"status": "skipped"},
        }
    }

    assert codex_sync_state.iter_nonterminal_paths(state) == [active]


def test_state_round_trip_is_atomic_and_corruption_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "state.json"
    replace_calls: list[tuple[Path, Path]] = []
    real_replace = codex_sync_state.os.replace

    def recording_replace(source, destination) -> None:
        replace_calls.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(codex_sync_state, "STATE_PATH", state_path)
    monkeypatch.setattr(codex_sync_state.os, "replace", recording_replace)
    payload: dict[str, object] = {"transcripts": {"/tmp/a.jsonl": {"status": "active"}}}

    codex_sync_state.save_state(payload)

    assert codex_sync_state.load_state() == payload
    assert len(replace_calls) == 1
    assert replace_calls[0][1] == state_path
    assert not replace_calls[0][0].exists()

    state_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="unreadable"):
        codex_sync_state.load_state()
