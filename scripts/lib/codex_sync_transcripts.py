"""Transcript discovery and parsing for codex-session-sync."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

TRANSCRIPTS_ROOT = Path.home() / ".codex" / "sessions"
PROC_ROOT = Path("/proc")
DEFAULT_MODEL = "unknown"
AICO_PERSONAL_PROJECT_ID = "__aico_personal_workspace__"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AGENT_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]{1,254}$")
_AICO_ENV_KEYS = frozenset({
    "AICO_AGENT_SLUG",
    "AICO_LIFECYCLE_VERSION",
    "AICO_OWNER",
    "AICO_PROJECT_ID",
    "AICO_SESSION_ID",
    "AICO_TMUX_SERVER_ID",
    "AICO_WIDGET_ID",
    "AICO_WORKLOAD_CLASS",
})


@dataclass(frozen=True)
class AicoProcessOwner:
    """Allow-listed AICO ownership identity inherited by a Codex process."""

    harness: str
    aico_session_id: str
    aico_widget_id: str
    aico_project_id: str


@dataclass(frozen=True)
class OpenTranscriptSnapshot:
    """Open Codex transcript paths and their validated AICO owners."""

    paths: frozenset[Path]
    owners: dict[Path, AicoProcessOwner]
    ambiguous_paths: frozenset[Path]

    @classmethod
    def empty(cls) -> OpenTranscriptSnapshot:
        return cls(paths=frozenset(), owners={}, ambiguous_paths=frozenset())


@dataclass(frozen=True)
class TranscriptInfo:
    path: Path
    session_id: str
    cwd: Path
    model: str
    mtime: float
    size: int
    parent_session_id: str | None = None
    agent_nickname: str | None = None
    agent_path: str | None = None
    is_open: bool = False
    process_owner: AicoProcessOwner | None = None
    ownership_ambiguous: bool = False
    native_session_id: str | None = None
    identity_error: str | None = None
    identity_scan: dict[str, object] = field(default_factory=dict)


def _safe_identifier(value: object) -> str:
    text = value if isinstance(value, str) else ""
    return text if _IDENTIFIER_RE.fullmatch(text) else ""


def _safe_display_identity(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 80:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def _safe_agent_path(value: object) -> str | None:
    if not isinstance(value, str) or not _AGENT_PATH_RE.fullmatch(value):
        return None
    if ".." in Path(value).parts:
        return None
    return value


def _subagent_identity(source: object) -> tuple[str | None, str | None, str | None]:
    if not isinstance(source, dict):
        return None, None, None
    subagent = source.get("subagent")
    if not isinstance(subagent, dict):
        return None, None, None
    spawn = subagent.get("thread_spawn")
    if not isinstance(spawn, dict):
        return None, None, None
    parent = _safe_identifier(spawn.get("parent_thread_id")) or None
    nickname = _safe_display_identity(spawn.get("agent_nickname"))
    agent_path = _safe_agent_path(spawn.get("agent_path"))
    return parent, nickname, agent_path


def _native_identity(payload: dict[str, object]) -> dict[str, object]:
    parent, nickname, agent_path = _subagent_identity(payload.get("source"))
    error = None
    for key, nested, validate in (
        ("parent_thread_id", parent, _safe_identifier),
        ("agent_path", agent_path, _safe_agent_path),
    ):
        raw = payload.get(key)
        if raw is not None:
            direct = validate(raw)
            if not direct or (nested and direct != nested):
                error = f"contradictory native {key} provenance"
            elif key == "parent_thread_id":
                parent = direct
            else:
                agent_path = direct
    session_id = _safe_identifier(payload.get("id"))
    native_session_id = _safe_identifier(payload.get("session_id"))
    if payload.get("session_id") is not None and not native_session_id:
        error = "invalid native runtime session provenance"
    source = payload.get("source")
    if isinstance(source, dict) and "subagent" in source and not parent:
        error = "invalid native subagent provenance"
    # A child may lack agent_path (guardian reviews, older thread_spawn headers);
    # it is still a child, never the root.
    if parent == session_id or (parent and agent_path == "/root"):
        error = "contradictory native child provenance"
    if not parent and agent_path not in {None, "/root"}:
        error = "native child agent path has no parent provenance"
    raw_cwd = payload.get("cwd")
    return {
        "session_id": session_id,
        "native_session_id": native_session_id or session_id,
        "cwd": raw_cwd if isinstance(raw_cwd, str) and Path(raw_cwd).is_absolute() else "",
        "parent_session_id": parent,
        "agent_nickname": nickname or _safe_display_identity(payload.get("agent_nickname")),
        "agent_path": agent_path,
        "identity_error": error,
        "history_start_ordinal": payload.get("subagent_history_start_ordinal"),
    }


def external_agent_path(info: object) -> str | None:
    """Agent path to assert: roots default to ``/root``; a pathless child asserts none."""
    agent_path = getattr(info, "agent_path", None)
    if agent_path:
        return agent_path
    return None if getattr(info, "parent_session_id", None) else "/root"


def _extract_transcript_fields(
    path: Path, previous: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Read native ownership provenance; Agent Hub alone interprets turn/model data."""
    stat = path.stat()
    file_generation = f"{stat.st_dev}:{stat.st_ino}"
    saved = previous or {}
    if saved.get("generation") != file_generation or int(saved.get("offset") or 0) > stat.st_size:
        saved = {}
    if saved:
        with path.open("rb") as prefix:
            head = prefix.read(int(saved.get("head_size") or 0))
            prefix.seek(int(saved.get("tail_start") or 0))
            tail = prefix.read(int(saved.get("offset") or 0) - int(saved.get("tail_start") or 0))
        if hashlib.sha256(head).hexdigest() != saved.get("head_digest") or hashlib.sha256(tail).hexdigest() != saved.get("tail_digest"):
            saved = {}
    generation = str(saved.get("source_generation") or file_generation)
    identity: dict[str, object] = dict(saved.get("identity") or {})
    line_number = int(saved.get("line_number") or 0)
    offset = int(saved.get("offset") or 0)
    with path.open("rb") as handle:
        handle.seek(offset)
        while line := handle.readline():
            if not line.endswith(b"\n"):
                break
            offset = handle.tell()
            line_number += 1
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(obj, dict) or obj.get("type") != "session_meta":
                continue
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                continue
            if not identity:
                identity = _native_identity(payload)
                generation += ":" + hashlib.sha256(line).hexdigest()
            elif payload.get("id") == identity["session_id"] and _native_identity(payload) != identity:
                identity["identity_error"] = "contradictory repeated native session provenance"
            # Fork history may contain a different parent's header. It cannot
            # replace the first immutable child identity.
        head_size = min(offset, 4096)
        tail_start = max(offset - 4096, 0)
        handle.seek(0)
        head_digest = hashlib.sha256(handle.read(head_size)).hexdigest()
        handle.seek(tail_start)
        tail_digest = hashlib.sha256(handle.read(offset - tail_start)).hexdigest()
    return identity, {
        "generation": file_generation, "source_generation": generation,
        "offset": offset, "line_number": line_number, "identity": identity,
        "head_size": head_size, "head_digest": head_digest,
        "tail_start": tail_start, "tail_digest": tail_digest,
    }


def resolve_current_transcript(
    environment: dict[str, str] | None = None,
    open_snapshot: OpenTranscriptSnapshot | None = None,
    caller_identity: dict[str, str] | None = None,
) -> TranscriptInfo:
    """Validate native thread identity; environment values are candidate hints."""
    env = os.environ if environment is None else environment
    session_hint = (env.get("CODEX_SESSION_ID") or "").strip()
    thread_hint = (env.get("CODEX_THREAD_ID") or "").strip()
    if not session_hint and not thread_hint:
        raise ValueError("No current Codex session identity is available for binding.")
    snapshot = open_snapshot or discover_open_transcripts()
    candidates = []
    for path in snapshot.paths:
        info = read_transcript_info(path, open_snapshot=snapshot)
        if info is not None and info.session_id in {session_hint, thread_hint}:
            candidates.append(info)
    if any(info.identity_error or info.ownership_ambiguous for info in candidates):
        raise ValueError("Conflicting native Codex transcript provenance.")
    by_id = {info.session_id: info for info in candidates}
    if len(by_id) != len(candidates):
        raise ValueError("Ambiguous native Codex transcript identity.")
    caller = _caller_native_identity() if caller_identity is None else caller_identity
    caller_thread = caller.get("CODEX_THREAD_ID") or caller.get("CODEX_SESSION_ID")
    if caller_thread:
        current = by_id.get(caller_thread)
        if current is None:
            raise ValueError("Caller native identity conflicts with supplied Codex environment identity.")
        caller_runtime = caller.get("CODEX_SESSION_ID")
        if caller_runtime and caller_runtime not in {current.session_id, current.native_session_id}:
            raise ValueError("Caller runtime session conflicts with native Codex provenance.")
        return current
    raise ValueError("Current native Codex identity requires validated caller provenance.")


def _caller_native_identity(proc_root: Path = PROC_ROOT) -> dict[str, str]:
    """Read only native ID hints from our initial process ancestry below Codex."""
    processes: list[dict[str, str]] = []
    pid = os.getpid()
    visited: set[int] = set()
    while pid > 1 and pid not in visited:
        visited.add(pid)
        process = proc_root / str(pid)
        parts = _read_cmdline(process)
        if _looks_like_codex_process(parts):
            identities = [item for item in processes if item]
            if not identities:
                return {}
            # The process closest to Codex was created by its native exec runtime;
            # intermediary launchers must not silently replace that identity.
            original = identities[-1]
            if any(item != original for item in identities):
                raise ValueError("Contradictory native caller ancestry identity.")
            return original
        if parts:
            try:
                raw = (process / "environ").read_bytes()
            except OSError:
                return {}
            identity: dict[str, str] = {}
            for item in raw.split(b"\0"):
                key, _, value = item.partition(b"=")
                if key in {b"CODEX_THREAD_ID", b"CODEX_SESSION_ID"}:
                    parsed = _safe_identifier(value.decode("utf-8", "ignore"))
                    if parsed:
                        identity[key.decode("ascii")] = parsed
            processes.append(identity)
        try:
            status = (process / "status").read_text(encoding="utf-8")
            pid = next(int(line.split()[1]) for line in status.splitlines() if line.startswith("PPid:"))
        except (OSError, ValueError, StopIteration):
            return {}
    return {}


def read_transcript_info(
    path: Path,
    log_fn: object = None,
    open_snapshot: OpenTranscriptSnapshot | None = None,
    scan_state: dict[str, object] | None = None,
) -> TranscriptInfo | None:
    """Parse native identity and advance the ownership-provenance cursor."""
    try:
        identity, identity_scan = _extract_transcript_fields(path, scan_state)
    except OSError as exc:
        if log_fn:
            log_fn(f"[WARN] Failed to read transcript {path}: {exc}")
        return None
    if not identity.get("session_id") or not identity.get("cwd"):
        return None
    try:
        stat = path.stat()
        resolved = path.expanduser().resolve(strict=False)
    except OSError as exc:
        if log_fn:
            log_fn(f"[WARN] Failed to stat transcript {path}: {exc}")
        return None
    snapshot = open_snapshot or OpenTranscriptSnapshot.empty()
    return TranscriptInfo(
        path=resolved,
        session_id=identity["session_id"],
        cwd=Path(identity["cwd"]),
        model=DEFAULT_MODEL,
        mtime=stat.st_mtime,
        size=stat.st_size,
        parent_session_id=identity["parent_session_id"],
        agent_nickname=identity["agent_nickname"],
        agent_path=identity["agent_path"],
        native_session_id=identity["native_session_id"],
        identity_error=identity["identity_error"],
        identity_scan=identity_scan,
        is_open=resolved in snapshot.paths,
        process_owner=snapshot.owners.get(resolved),
        ownership_ambiguous=resolved in snapshot.ambiguous_paths,
    )


def iter_recent_transcripts(
    recent_hours: int,
    log_fn: object = None,
    open_snapshot: OpenTranscriptSnapshot | None = None,
    scan_states: dict[str, object] | None = None,
) -> list[TranscriptInfo]:
    if not TRANSCRIPTS_ROOT.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(hours=recent_hours)
    transcripts: list[TranscriptInfo] = []
    for path in TRANSCRIPTS_ROOT.rglob("*.jsonl"):
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        except OSError:
            continue
        if modified_at < cutoff:
            continue
        entry = (scan_states or {}).get(str(path.resolve()))
        scan_state = (entry.get("identity_scan") or entry.get("model_scan")) if isinstance(entry, dict) else None
        info = read_transcript_info(path, log_fn=log_fn, open_snapshot=open_snapshot, scan_state=scan_state)
        if info is not None:
            transcripts.append(info)
    transcripts.sort(key=lambda item: item.mtime)
    return transcripts


def _proc_entries(proc_root: Path = PROC_ROOT) -> list[Path]:
    try:
        return [path for path in proc_root.iterdir() if path.name.isdigit()]
    except OSError:
        return []


def _read_cmdline(proc_dir: Path) -> list[str]:
    try:
        raw = (proc_dir / "cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", "ignore") for part in raw.split(b"\0") if part]


def _looks_like_codex_process(parts: list[str]) -> bool:
    return any(Path(part).name == "codex" for part in parts)


def has_live_codex_process(proc_root: Path = PROC_ROOT) -> bool:
    """Return True when a live process looks like a Codex CLI wrapper or binary."""
    for proc_dir in _proc_entries(proc_root):
        if _looks_like_codex_process(_read_cmdline(proc_dir)):
            return True
    return False


def _read_allowlisted_aico_environment(proc_dir: Path) -> dict[str, str]:
    try:
        raw = (proc_dir / "environ").read_bytes()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if b"=" not in item:
            continue
        raw_key, raw_value = item.split(b"=", 1)
        key = raw_key.decode("ascii", "ignore")
        if key not in _AICO_ENV_KEYS:
            continue
        values[key] = raw_value.decode("utf-8", "ignore")[:256]
    return values


def _validated_aico_owner(environment: dict[str, str]) -> tuple[AicoProcessOwner | None, bool]:
    """Return (owner, invalid_marker) without retaining the process environment."""
    marker = environment.get("AICO_OWNER")
    if marker is None:
        return None, False
    if marker != "aico" or environment.get("AICO_WORKLOAD_CLASS") != "durable-session":
        return None, True
    if environment.get("AICO_LIFECYCLE_VERSION") != "1":
        return None, True

    harness = _safe_identifier(environment.get("AICO_AGENT_SLUG"))
    session_id = _safe_identifier(environment.get("AICO_SESSION_ID"))
    widget_id = _safe_identifier(environment.get("AICO_WIDGET_ID"))
    project_id = environment.get("AICO_PROJECT_ID", "")
    if (
        project_id
        and project_id != AICO_PERSONAL_PROJECT_ID
        and not _safe_identifier(project_id)
    ):
        return None, True
    server_id = environment.get("AICO_TMUX_SERVER_ID", "")
    if server_id and not re.fullmatch(r"[a-f0-9]{8,64}", server_id):
        return None, True
    if harness != "codex" or not session_id or not widget_id:
        return None, True
    return (
        AicoProcessOwner(
            harness=harness,
            aico_session_id=session_id,
            aico_widget_id=widget_id,
            aico_project_id=project_id,
        ),
        False,
    )


def _resolved_transcript_target(fd: Path, root: Path) -> Path | None:
    try:
        target = os.readlink(fd)
    except OSError:
        return None
    target = target.removesuffix(" (deleted)")
    if not target.endswith(".jsonl"):
        return None
    target_path = Path(target)
    if not target_path.is_absolute():
        return None
    try:
        resolved = target_path.resolve(strict=False)
    except OSError:
        resolved = target_path
    return resolved if resolved.is_relative_to(root) else None


def discover_open_transcripts(
    *,
    proc_root: Path = PROC_ROOT,
    transcripts_root: Path = TRANSCRIPTS_ROOT,
) -> OpenTranscriptSnapshot:
    """Discover live Codex rollouts and validated AICO ownership from /proc."""
    try:
        root = transcripts_root.expanduser().resolve(strict=False)
    except OSError:
        root = transcripts_root.expanduser()

    paths: set[Path] = set()
    owners: dict[Path, AicoProcessOwner] = {}
    ambiguous: set[Path] = set()
    for proc_dir in _proc_entries(proc_root):
        if not _looks_like_codex_process(_read_cmdline(proc_dir)):
            continue
        environment = _read_allowlisted_aico_environment(proc_dir)
        owner, invalid_owner = _validated_aico_owner(environment)
        try:
            fds = list((proc_dir / "fd").iterdir())
        except OSError:
            continue
        for fd in fds:
            resolved = _resolved_transcript_target(fd, root)
            if resolved is None:
                continue
            paths.add(resolved)
            if invalid_owner:
                ambiguous.add(resolved)
                owners.pop(resolved, None)
                continue
            if owner is None or resolved in ambiguous:
                continue
            previous = owners.get(resolved)
            if previous is not None and previous != owner:
                ambiguous.add(resolved)
                owners.pop(resolved, None)
                continue
            owners[resolved] = owner
    return OpenTranscriptSnapshot(
        paths=frozenset(paths),
        owners=owners,
        ambiguous_paths=frozenset(ambiguous),
    )


def iter_open_transcript_paths(
    *,
    proc_root: Path = PROC_ROOT,
    transcripts_root: Path = TRANSCRIPTS_ROOT,
) -> set[Path]:
    """Return Codex transcript files currently held open by live host processes."""
    return set(
        discover_open_transcripts(
            proc_root=proc_root,
            transcripts_root=transcripts_root,
        ).paths
    )
