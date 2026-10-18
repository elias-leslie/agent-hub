"""State management for codex-session-sync: load, save, update, and check."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

STATE_PATH = Path.home() / ".local" / "state" / "codex-session-sync" / "state.json"
ERROR_RETRY_SECONDS = 300
HEARTBEAT_INTERVAL_SECONDS = 30
PERMANENT_HTTP_STATUSES = frozenset({400, 403, 404, 409, 410, 422})


def load_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        return {"transcripts": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Codex sync state is unreadable") from exc
    if not isinstance(data, dict):
        raise ValueError("Codex sync state must be a JSON object")
    return data


def save_state(state: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=STATE_PATH.parent,
            prefix=f".{STATE_PATH.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(state, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fchmod(handle.fileno(), 0o600)
            os.fsync(handle.fileno())
        os.replace(temporary_path, STATE_PATH)
        temporary_path = None
        directory_fd = os.open(STATE_PATH.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _transcripts_map(state: dict[str, object], *, create: bool = False) -> dict[str, object] | None:
    transcripts = state.get("transcripts")
    if isinstance(transcripts, dict):
        return cast(dict[str, object], transcripts)
    if not create:
        return None
    transcripts = {}
    state["transcripts"] = transcripts
    return transcripts


def get_state_entry(path: Path, state: dict[str, object]) -> dict[str, object] | None:
    entries = _transcripts_map(state)
    if entries is None:
        return None
    entry = entries.get(str(path))
    return cast(dict[str, object], entry) if isinstance(entry, dict) else None


def update_state_entry(
    state: dict[str, object],
    path: Path,
    session_id: str,
    mtime: float,
    size: int,
    status: str,
    detail: str,
    checkpoint: str | None = None,
    preserve_checkpoint: bool = True,
    identity_fingerprint: str | None = None,
    project_binding_fingerprint: str | None = None,
    heartbeat_at: str | None = None,
    rejected_identity: str | None = None,
    identity_scan: dict[str, object] | None = None,
) -> None:
    transcripts = _transcripts_map(state, create=True)
    assert transcripts is not None
    previous = get_state_entry(path, state) or {}
    transcripts[str(path)] = {
        "session_id": session_id,
        "mtime": mtime,
        "size": size,
        "status": status,
        "detail": detail,
        "checkpoint": (
            checkpoint
            if checkpoint is not None
            else (previous.get("checkpoint") if preserve_checkpoint else None)
        ),
        "identity_fingerprint": (
            identity_fingerprint
            if identity_fingerprint is not None
            else previous.get("identity_fingerprint")
        ),
        "project_binding_fingerprint": (
            project_binding_fingerprint
            if project_binding_fingerprint is not None
            else previous.get("project_binding_fingerprint")
        ),
        "last_heartbeat_at": (
            heartbeat_at if heartbeat_at is not None else previous.get("last_heartbeat_at")
        ),
        "updated_at": datetime.now(UTC).isoformat(),
        "rejected_identity": rejected_identity if rejected_identity is not None else previous.get("rejected_identity"),
        "identity_scan": identity_scan if identity_scan is not None else (previous.get("identity_scan") or previous.get("model_scan")),
    }


def should_sync(
    path: Path,
    mtime: float,
    size: int,
    state: dict[str, object],
    force: bool,
    *,
    close_session: bool = False,
) -> bool:
    if force:
        return True
    entry = get_state_entry(path, state)
    if entry is None:
        return True
    if entry_is_permanent_error(entry):
        return False
    if close_session:
        return entry.get("status") not in {"terminal", "skipped"}
    if entry.get("status") == "terminal":
        return False
    if entry.get("mtime") != mtime or entry.get("size") != size:
        return True
    if entry.get("status") != "error":
        return False
    return _error_retry_due(entry)


def should_heartbeat(
    path: Path,
    state: dict[str, object],
    *,
    force: bool = False,
    now: datetime | None = None,
    interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS,
) -> bool:
    """Return True when a live transcript needs a collector heartbeat."""
    if force:
        return True
    entry = get_state_entry(path, state)
    if entry is None:
        return True
    if entry.get("status") in {"terminal", "skipped"} or entry_is_permanent_error(entry):
        return False
    if entry.get("status") == "error":
        return _error_retry_due(entry)
    heartbeat_at = entry.get("last_heartbeat_at")
    if not isinstance(heartbeat_at, str) or not heartbeat_at:
        return True
    try:
        last_heartbeat = datetime.fromisoformat(heartbeat_at)
    except ValueError:
        return True
    if last_heartbeat.tzinfo is None:
        last_heartbeat = last_heartbeat.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    return (current - last_heartbeat).total_seconds() >= interval_seconds


def iter_nonterminal_paths(state: dict[str, object]) -> list[Path]:
    """Return tracked paths that may need a deterministic inactive close pass."""
    entries = _transcripts_map(state)
    if entries is None:
        return []
    paths: list[Path] = []
    for raw_path, raw_entry in entries.items():
        if not isinstance(raw_path, str) or not isinstance(raw_entry, dict):
            continue
        if raw_entry.get("status") in {"terminal", "skipped"} or entry_is_permanent_error(raw_entry):
            continue
        paths.append(Path(raw_path))
    return paths


def get_checkpoint(path: Path, state: dict[str, object]) -> str | None:
    entry = get_state_entry(path, state)
    if entry is None:
        return None
    checkpoint = entry.get("checkpoint")
    return checkpoint if isinstance(checkpoint, str) else None


def entry_is_permanent_error(entry: dict[str, object]) -> bool:
    status = str(entry.get("status") or "")
    if status == "permanent_error":
        return True
    if status != "error":
        return False
    detail = str(entry.get("detail") or "")
    match = re.search(r"\bstatus=(\d{3})\b", detail)
    return bool(match and int(match[1]) in PERMANENT_HTTP_STATUSES)


def _error_retry_due(entry: dict[str, object]) -> bool:
    updated_at = entry.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at:
        return True
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return (datetime.now(UTC) - updated).total_seconds() >= ERROR_RETRY_SECONDS
