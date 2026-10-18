from __future__ import annotations

import importlib
import sys
from dataclasses import asdict
from pathlib import Path

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

codex_sync_transcripts = importlib.import_module("codex_sync_transcripts")


def _owner_environment(*, widget: str = "d24ad045", project: str = "a-loom") -> bytes:
    values = {
        "AICO_OWNER": "aico",
        "AICO_WORKLOAD_CLASS": "durable-session",
        "AICO_LIFECYCLE_VERSION": "1",
        "AICO_AGENT_SLUG": "codex",
        "AICO_SESSION_ID": f"aico-widget-{widget}",
        "AICO_WIDGET_ID": widget,
        "AICO_PROJECT_ID": project,
        "AICO_TMUX_SERVER_ID": "18e25b04d4ff0a47e5859c7d547a5054",
        "AGENT_HUB_TOKEN": "must-not-be-copied",
    }
    return b"\0".join(f"{key}={value}".encode() for key, value in values.items()) + b"\0"


def _process(
    proc_root: Path,
    pid: str,
    transcript: Path,
    environment: bytes,
) -> None:
    proc_dir = proc_root / pid
    fd_dir = proc_dir / "fd"
    fd_dir.mkdir(parents=True)
    (proc_dir / "cmdline").write_bytes(b"/opt/codex/bin/codex\0")
    (proc_dir / "environ").write_bytes(environment)
    (fd_dir / "26").symlink_to(transcript)


def test_discover_open_transcripts_retains_only_allowlisted_aico_owner(tmp_path: Path) -> None:
    transcripts_root = tmp_path / "sessions"
    transcript = transcripts_root / "rollout.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _process(proc_root, "123", transcript, _owner_environment())

    snapshot = codex_sync_transcripts.discover_open_transcripts(
        proc_root=proc_root,
        transcripts_root=transcripts_root,
    )

    owner = snapshot.owners[transcript.resolve()]
    assert asdict(owner) == {
        "harness": "codex",
        "aico_session_id": "aico-widget-d24ad045",
        "aico_widget_id": "d24ad045",
        "aico_project_id": "a-loom",
    }
    assert "AGENT_HUB_TOKEN" not in asdict(owner)
    assert not snapshot.ambiguous_paths


def test_invalid_aico_owner_fails_closed_as_ambiguous(tmp_path: Path) -> None:
    transcripts_root = tmp_path / "sessions"
    transcript = transcripts_root / "rollout.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n", encoding="utf-8")
    proc_root = tmp_path / "proc"
    environment = _owner_environment().replace(
        b"AICO_LIFECYCLE_VERSION=1",
        b"AICO_LIFECYCLE_VERSION=999",
    )
    _process(proc_root, "123", transcript, environment)

    snapshot = codex_sync_transcripts.discover_open_transcripts(
        proc_root=proc_root,
        transcripts_root=transcripts_root,
    )

    assert transcript.resolve() in snapshot.paths
    assert transcript.resolve() in snapshot.ambiguous_paths
    assert transcript.resolve() not in snapshot.owners


def test_personal_workspace_sentinel_is_valid_owner_but_not_a_project_mapping(
    tmp_path: Path,
) -> None:
    transcripts_root = tmp_path / "sessions"
    transcript = transcripts_root / "rollout.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _process(
        proc_root,
        "123",
        transcript,
        _owner_environment(project="__aico_personal_workspace__"),
    )

    snapshot = codex_sync_transcripts.discover_open_transcripts(
        proc_root=proc_root,
        transcripts_root=transcripts_root,
    )

    assert snapshot.owners[transcript.resolve()].aico_project_id == (
        "__aico_personal_workspace__"
    )
    assert transcript.resolve() not in snapshot.ambiguous_paths


def test_conflicting_aico_owners_fail_closed_as_ambiguous(tmp_path: Path) -> None:
    transcripts_root = tmp_path / "sessions"
    transcript = transcripts_root / "rollout.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n", encoding="utf-8")
    proc_root = tmp_path / "proc"
    _process(proc_root, "123", transcript, _owner_environment(widget="d24ad045"))
    _process(proc_root, "456", transcript, _owner_environment(widget="35f62654"))

    snapshot = codex_sync_transcripts.discover_open_transcripts(
        proc_root=proc_root,
        transcripts_root=transcripts_root,
    )

    assert transcript.resolve() in snapshot.ambiguous_paths
    assert transcript.resolve() not in snapshot.owners
