"""Caller-supplied paths stay inside their allowed roots (CodeQL path-injection fixes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.session_ingestion.adapters import transcript_parsers
from app.services.tools import _executor_roots


def test_transcripts_outside_the_roots_are_never_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed, outside = tmp_path / "sessions", tmp_path / "elsewhere"
    allowed.mkdir()
    outside.mkdir()
    header = '{"type": "session_meta", "payload": {"id": "s1"}}\n'
    (allowed / "t.jsonl").write_text(header)
    (outside / "t.jsonl").write_text(header)
    monkeypatch.setenv("AGENT_HUB_TRANSCRIPT_ROOTS", str(allowed))

    assert transcript_parsers.transcript_session_identity(str(allowed / "t.jsonl")) == "s1"
    assert transcript_parsers.transcript_session_metadata(str(outside / "t.jsonl")) is None
    assert transcript_parsers.transcript_session_metadata(str(allowed / ".." / "elsewhere" / "t.jsonl")) is None
    assert transcript_parsers.read_jsonl_lines(str(outside / "t.jsonl")) == ([], None)
    assert transcript_parsers.inspect_transcript_source(str(outside / "t.jsonl"), None).state == "blocked"


def test_working_dir_must_sit_in_a_known_root_worktree_or_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "project"
    (root / ".git" / "worktrees" / "lane").mkdir(parents=True)
    worktree = Path("/proc/self")  # stands in for a directory outside every base
    monkeypatch.setattr(_executor_roots, "_get_known_roots", lambda: {"p": str(root)})
    monkeypatch.setattr(_executor_roots.tempfile, "gettempdir", lambda: str(tmp_path / "scratch"))
    (tmp_path / "scratch").mkdir()

    assert _executor_roots.contained_working_dir(str(root)) == root.resolve()
    assert _executor_roots.contained_working_dir(str(tmp_path / "scratch")) == (tmp_path / "scratch").resolve()
    with pytest.raises(ValueError, match="outside"):
        _executor_roots.contained_working_dir("/etc")
    with pytest.raises(ValueError, match="not an existing directory"):
        _executor_roots.contained_working_dir(str(root / "missing"))
    assert not (root / "missing").exists()

    (root / ".git" / "worktrees" / "lane" / "gitdir").write_text(f"{worktree}/.git\n")
    assert _executor_roots.contained_working_dir(str(worktree)) == worktree.resolve()


def test_a_sibling_sharing_the_root_prefix_is_outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, evil = tmp_path / "root", tmp_path / "root-evil"
    root.mkdir()
    evil.mkdir()
    (evil / "t.jsonl").write_text('{"type": "session_meta", "payload": {"id": "s1"}}\n')
    monkeypatch.setenv("AGENT_HUB_TRANSCRIPT_ROOTS", str(root))
    monkeypatch.setattr(_executor_roots, "_get_known_roots", lambda: {"p": str(root)})
    monkeypatch.setattr(_executor_roots.tempfile, "gettempdir", lambda: str(root / "scratch"))

    assert transcript_parsers.contained_transcript_path(str(evil / "t.jsonl")) is None
    assert transcript_parsers.contained_transcript_path(str(root)) == root.resolve()
    with pytest.raises(ValueError, match="outside"):
        _executor_roots.contained_working_dir(str(evil))
