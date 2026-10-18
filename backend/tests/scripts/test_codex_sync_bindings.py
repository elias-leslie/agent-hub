from __future__ import annotations

import fcntl
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

bindings_module = importlib.import_module("codex_sync_bindings")
BindingConflict = bindings_module.BindingConflict
ProjectBinding = bindings_module.ProjectBinding
bind_project = bindings_module.bind_project
binding_fingerprint = bindings_module.binding_fingerprint
load_snapshot = bindings_module.load_snapshot
save_snapshot_locked = bindings_module.save_snapshot_locked
sync_lock = bindings_module.sync_lock


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    state_dir = tmp_path / "codex-session-sync"
    return state_dir / "project-bindings.json", state_dir / "sync.lock"


def _binding(session_id: str = "session-1") -> ProjectBinding:
    return ProjectBinding(
        session_id=session_id,
        project_id="rootfall",
        project_root="/srv/workspaces/projects/rootfall",
        bound_at="2026-07-15T12:00:00Z",
        source="explicit",
    )


def test_snapshot_round_trip_uses_allowlisted_versioned_schema(tmp_path: Path) -> None:
    bindings_path, lock_path = _paths(tmp_path)
    binding = _binding()

    with sync_lock(lock_path):
        save_snapshot_locked({binding.session_id: binding}, bindings_path)

    assert load_snapshot(bindings_path) == {binding.session_id: binding}
    serialized = json.loads(bindings_path.read_text(encoding="utf-8"))
    assert set(serialized) == {"version", "bindings"}
    assert serialized["version"] == 1
    assert set(serialized["bindings"][binding.session_id]) == {
        "session_id",
        "project_id",
        "project_root",
        "bound_at",
        "source",
        "parent_session_id",
    }
    assert binding.fingerprint == binding_fingerprint(load_snapshot(bindings_path)[binding.session_id])


def test_bind_project_is_idempotent_without_rewriting_binding_metadata(tmp_path: Path) -> None:
    bindings_path, lock_path = _paths(tmp_path)
    first = bind_project(
        "session-1",
        "rootfall",
        "/srv/workspaces/projects/rootfall/.",
        "explicit",
        bindings_path=bindings_path,
        lock_path=lock_path,
        bound_at="2026-07-15T12:00:00Z",
    )

    confirmed = bind_project(
        "session-1",
        "rootfall",
        "/srv/workspaces/projects/rootfall",
        "inherited",
        "parent-2",
        bindings_path=bindings_path,
        lock_path=lock_path,
        bound_at="2026-07-16T12:00:00Z",
    )

    assert confirmed is not first
    assert confirmed == first
    assert confirmed.source == "explicit"
    assert confirmed.bound_at == "2026-07-15T12:00:00Z"
    assert confirmed.parent_session_id is None


def test_bind_project_rejects_conflicting_project_or_root(tmp_path: Path) -> None:
    bindings_path, lock_path = _paths(tmp_path)
    existing = bind_project(
        "session-1",
        "rootfall",
        "/srv/workspaces/projects/rootfall",
        "explicit",
        bindings_path=bindings_path,
        lock_path=lock_path,
        bound_at="2026-07-15T12:00:00Z",
    )

    with pytest.raises(BindingConflict) as error:
        bind_project(
            "session-1",
            "a-loom",
            "/srv/workspaces/projects/a-loom",
            "explicit",
            bindings_path=bindings_path,
            lock_path=lock_path,
            bound_at="2026-07-15T12:01:00Z",
        )

    assert error.value.existing == existing
    assert error.value.requested.project_id == "a-loom"
    assert load_snapshot(bindings_path) == {"session-1": existing}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_id", "../escape"),
        ("project_id", "rootfall/other"),
        ("project_root", "relative/rootfall"),
        ("bound_at", ""),
        ("source", "guessed"),
        ("parent_session_id", "bad parent"),
    ],
)
def test_project_binding_rejects_unsafe_fields(field: str, value: str) -> None:
    values: dict[str, object] = {
        "session_id": "session-1",
        "project_id": "rootfall",
        "project_root": "/srv/workspaces/projects/rootfall",
        "bound_at": "2026-07-15T12:00:00Z",
        "source": "inherited",
        "parent_session_id": "parent-1",
    }
    values[field] = value

    with pytest.raises(ValueError):
        ProjectBinding(**values)


@pytest.mark.parametrize(
    ("source", "parent_session_id"),
    [
        ("explicit", "parent-1"),
        ("inherited", None),
        ("inherited", "session-1"),
    ],
)
def test_project_binding_enforces_source_parent_invariants(
    source: str,
    parent_session_id: str | None,
) -> None:
    with pytest.raises(ValueError):
        ProjectBinding(
            session_id="session-1",
            project_id="rootfall",
            project_root="/srv/workspaces/projects/rootfall",
            bound_at="2026-07-15T12:00:00Z",
            source=source,
            parent_session_id=parent_session_id,
        )


def test_load_snapshot_rejects_unknown_top_level_or_binding_fields(tmp_path: Path) -> None:
    bindings_path, _ = _paths(tmp_path)
    bindings_path.parent.mkdir(parents=True)
    binding_payload: dict[str, object] = {
        "session_id": "session-1",
        "project_id": "rootfall",
        "project_root": "/srv/workspaces/projects/rootfall",
        "bound_at": "2026-07-15T12:00:00Z",
        "source": "explicit",
        "parent_session_id": None,
    }
    bindings_path.write_text(
        json.dumps({"version": 1, "bindings": {"session-1": binding_payload}, "extra": True}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="only version and bindings"):
        load_snapshot(bindings_path)

    binding_payload["extra"] = True
    bindings_path.write_text(
        json.dumps({"version": 1, "bindings": {"session-1": binding_payload}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="only the supported fields"):
        load_snapshot(bindings_path)

    bindings_path.write_text(
        json.dumps({"version": True, "bindings": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported project binding snapshot version"):
        load_snapshot(bindings_path)


def test_snapshot_rejects_missing_parent_and_cycles(tmp_path: Path) -> None:
    bindings_path, _ = _paths(tmp_path)
    bindings_path.parent.mkdir(parents=True)

    def payload(session_id: str, parent_session_id: str) -> dict[str, object]:
        return {
            "session_id": session_id,
            "project_id": "rootfall",
            "project_root": "/srv/workspaces/projects/rootfall",
            "bound_at": "2026-07-15T12:00:00Z",
            "source": "inherited",
            "parent_session_id": parent_session_id,
        }

    bindings_path.write_text(
        json.dumps({"version": 1, "bindings": {"child": payload("child", "missing")}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="parent is missing"):
        load_snapshot(bindings_path)

    bindings_path.write_text(
        json.dumps(
            {
                "version": 1,
                "bindings": {
                    "child-a": payload("child-a", "child-b"),
                    "child-b": payload("child-b", "child-a"),
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="contains a cycle"):
        load_snapshot(bindings_path)


def test_save_snapshot_locked_fsyncs_before_atomic_replace(tmp_path: Path, monkeypatch) -> None:
    bindings_path, lock_path = _paths(tmp_path)
    fsync_calls: list[int] = []
    replace_calls: list[tuple[Path, Path]] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def recording_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        real_fsync(fd)

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        replace_calls.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(bindings_module.os, "fsync", recording_fsync)
    monkeypatch.setattr(bindings_module.os, "replace", recording_replace)

    with sync_lock(lock_path):
        save_snapshot_locked({"session-1": _binding()}, bindings_path)

    assert len(fsync_calls) == 2
    assert len(replace_calls) == 1
    temporary_path, destination = replace_calls[0]
    assert temporary_path.parent == bindings_path.parent
    assert destination == bindings_path
    assert not temporary_path.exists()


def test_sync_lock_uses_exclusive_sidecar_flock(tmp_path: Path, monkeypatch) -> None:
    _, lock_path = _paths(tmp_path)
    operations: list[int] = []

    def recording_flock(_fd: int, operation: int) -> None:
        operations.append(operation)

    monkeypatch.setattr(bindings_module.fcntl, "flock", recording_flock)

    with sync_lock(lock_path):
        assert lock_path.exists()

    assert operations == [fcntl.LOCK_EX, fcntl.LOCK_UN]
