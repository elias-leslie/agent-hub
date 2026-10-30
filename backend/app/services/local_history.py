"""Keep local agent-harness history short once Agent Hub holds a full copy.

Agent Hub is the record of agent history. Claude Code, Codex and Pi also keep their own transcripts on
this machine; those copies are only needed to resume a recent session (Tether after a reboot, ``claude
--resume``, ``codex resume``). Each run:

1. catches up Claude Code: a turn that ended without a Stop hook (window closed, crash) and records
   written after the last Stop are ingested, and every subagent transcript under ``<session>/subagents/``
   (workflow agents included) is recorded as a child session of its parent;
2. deletes a local transcript only when it has been idle for ``local_history_retention_days``, no
   process has it open, no ``local_history_exclude_globs`` pattern matches it, Agent Hub's committed
   import cursor covers that exact content (cursor at its last byte, same tail digest; same device and
   inode for a plain file), the parser lost no record to a malformed line, and Agent Hub still holds the
   session's events. Everything deleted with it (a Claude Code session's other transcripts, the threads a
   Codex thread spawned) must pass the same guard.

Records the parser skips by type are not messages or tool calls (Claude Code titles, attachments and
request blobs; Codex tool lists and compaction blobs), so they do not block deletion.

Anything else is kept and counted by reason. Codex threads are removed with ``codex delete``, which also
drops them from Codex's own thread stores; the SQLite space that frees is then handed back to the disk
with ``PRAGMA incremental_vacuum`` (Codex creates those databases with incremental auto-vacuum).
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import logging
import os
import shlex
import shutil
import sqlite3
import subprocess
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Session, SessionEvent
from app.services.session_ingestion.adapters.claude_code import first_transcript_model
from app.services.session_ingestion.adapters.transcript_parsers import _load_parse_checkpoint
from app.services.session_ingestion.models import SessionUpsertRequest, TranscriptIngestRequest
from app.services.session_ingestion.service import ingest_transcript_events, upsert_session
from app.services.session_operations import close_session_if_active
from app.utils.native_homes import (
    claude_project_roots,
    codex_session_roots,
    host_homes_root,
    pi_session_roots,
)
from app.utils.safe_subprocess import bash_argv, run_process

logger = logging.getLogger(__name__)

# Child session ids for Claude Code subagents: stable per parent and agent file, and 36 chars like the rest.
_SUBAGENT_NAMESPACE = uuid.UUID("5b0c1d8e-6f43-4b8a-9a52-2f0f6c7d3e11")
_ZST = ".zst"
_TAIL_BYTES = 128  # transcript_parsers._tail_digest
_VACUUM_PAGES = 2048
# Parser issues where a whole line was unreadable, so its content may be missing from Agent Hub.
_LOSSY_PARSE_ISSUES = frozenset({"malformed_json", "invalid_utf8", "non_object_json", "unsupported_record_shape"})


def subagent_session_id(parent_session_id: str, relative_path: str) -> str:
    """``relative_path`` is the agent transcript's path inside the parent's session folder."""
    return str(uuid.uuid5(_SUBAGENT_NAMESPACE, f"{parent_session_id}/{relative_path}"))


def _source_key(path: Path) -> str:
    """The transcript path Agent Hub registered: Codex later compresses ``x.jsonl`` to ``x.jsonl.zst``."""
    text = str(path)
    return text[: -len(_ZST)] if text.endswith(_ZST) else text


def _tail(data: bytes) -> str:
    return hashlib.sha256(data[-_TAIL_BYTES:]).hexdigest()


@dataclass(frozen=True, slots=True)
class ImportCursor:
    """Agent Hub's committed position in one transcript, and what the session is about."""

    session_id: str
    device: int | None
    inode: int | None
    byte_offset: int
    tail_digest: str | None
    events_held: bool = True
    lossy: bool = False
    labels: tuple[str, ...] = ()
    children: tuple[str, ...] = ()
    duplicate: bool = False

    def same_source(self, stat: os.stat_result) -> bool:
        return (self.device, self.inode) == (stat.st_dev, stat.st_ino) and self.byte_offset <= stat.st_size

    def covers(self, path: Path) -> bool:
        """True when the committed cursor sits at the end of this file's (decompressed) content."""
        if path.name.endswith(_ZST):
            size, tail = _zst_extent(path)
            return size == self.byte_offset and tail == self.tail_digest
        stat = path.stat()
        if not self.same_source(stat) or self.byte_offset != stat.st_size:
            return False
        with path.open("rb") as transcript:
            transcript.seek(max(0, self.byte_offset - _TAIL_BYTES))
            return _tail(transcript.read(_TAIL_BYTES)) == self.tail_digest


def _zst_extent(path: Path) -> tuple[int, str]:
    """Decompressed size and the digest of its last bytes, streamed through the zstd CLI (never buffered)."""
    source = shlex.quote(str(path))
    stream = f"zstd -dcq -- {source}"
    result = run_process(
        bash_argv(f"set -o pipefail; {stream} | wc -c && {stream} | tail -c {_TAIL_BYTES} | od -An -v -tx1"),
        capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL,
    )
    lines = result.stdout.split("\n", 1)
    if result.returncode != 0 or len(lines) < 2:
        raise OSError(f"zstd could not read {path.name}")
    return int(lines[0]), _tail(bytes.fromhex("".join(lines[1].split())))


def _cursor(session: Session, *, events_held: bool = True, children: tuple[str, ...] = ()) -> ImportCursor | None:
    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    ingestion = metadata.get("transcript_ingestion")
    checkpoint = ingestion.get("checkpoint") if isinstance(ingestion, dict) else None
    parsed = _load_parse_checkpoint(checkpoint if isinstance(checkpoint, str) else None)
    if parsed.legacy or parsed.inode is None:
        return None
    labels = tuple(
        str(value) for value in (session.project_id, metadata.get("cwd"), metadata.get("repo_root")) if value
    )
    return ImportCursor(
        session.id, parsed.device, parsed.inode, parsed.byte_offset, parsed.tail_digest,
        events_held=events_held, lossy=bool(_LOSSY_PARSE_ISSUES & set(parsed.parse_issue_counts)),
        labels=labels, children=children,
    )


@dataclass(slots=True)
class HistoryUnit:
    """Files deleted together: one transcript plus its sidecar directory, if any."""

    harness: str
    transcript: Path
    sidecar: Path | None = None
    # Further transcripts deleted with it, which must pass the guard too (Claude Code subagents, workflow
    # journals; Codex threads this one spawned are added from Codex's spawn edges).
    dependents: list[Path] = field(default_factory=list)
    codex_home: Path | None = None

    def paths(self) -> list[Path]:
        # Sidecar first: an interrupted delete then leaves the transcript, which the next run finds again.
        return [*([self.sidecar] if self.sidecar else []), self.transcript]


@dataclass(slots=True)
class StoreReport:
    deleted: int = 0
    freed_bytes: int = 0
    kept: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {"deleted": self.deleted, "freed_bytes": self.freed_bytes, "kept": dict(self.kept)}


def local_roots(roots: Iterable[Path]) -> list[Path]:
    """Roots on this machine; Agent Hub's own copies of remote hosts' transcripts are never pruned."""
    host_root = os.path.realpath(host_homes_root())
    return [root for root in roots if not os.path.realpath(root).startswith(host_root + os.sep)]


def claude_units(root: Path) -> Iterator[HistoryUnit]:
    for transcript in sorted(root.glob("*/*.jsonl")):
        sidecar = transcript.with_suffix("")
        unit = HistoryUnit("claude_code", transcript, sidecar if sidecar.is_dir() else None)
        if unit.sidecar is not None:
            unit.dependents = sorted(unit.sidecar.rglob("*.jsonl"))
        yield unit


def flat_units(harness: str, root: Path, *patterns: str, codex_home: Path | None = None) -> Iterator[HistoryUnit]:
    for pattern in patterns:
        for transcript in sorted(root.glob(pattern)):
            yield HistoryUnit(harness, transcript, codex_home=codex_home)


def _discover() -> list[HistoryUnit]:
    units: list[HistoryUnit] = []
    for root in local_roots(claude_project_roots()):
        units.extend(claude_units(root))
    for root in local_roots(codex_session_roots()):
        units.extend(flat_units(
            "codex", root, "*/*/*/rollout-*.jsonl", "*/*/*/rollout-*.jsonl.zst", codex_home=root.parent,
        ))
    for root in local_roots(pi_session_roots()):
        units.extend(flat_units("pi", root, "*/*.jsonl"))
    return units


def _latest_mtime(unit: HistoryUnit) -> float:
    latest = unit.transcript.stat().st_mtime
    if unit.sidecar is not None:
        for directory, _, files in os.walk(unit.sidecar):
            latest = max(latest, os.stat(directory).st_mtime)
            for name in files:
                try:
                    latest = max(latest, os.lstat(os.path.join(directory, name)).st_mtime)
                except OSError:
                    continue
    return latest


def _size(unit: HistoryUnit) -> int:
    total = 0
    for path in unit.paths():
        if path.is_dir():
            for directory, _, files in os.walk(path):
                total += sum(os.lstat(os.path.join(directory, name)).st_size for name in files)
        else:
            total += path.stat().st_size
    return total


def open_paths() -> set[str]:
    """Real paths of files any process on this machine has open."""
    found: set[str] = set()
    for fd_dir in Path("/proc").glob("[0-9]*/fd"):
        try:
            entries = list(fd_dir.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                found.add(os.readlink(entry))
            except OSError:
                continue
    return found


def _existing(source: str) -> Path | None:
    for candidate in (Path(source), Path(source + _ZST)):
        if candidate.exists():
            return candidate
    return None


def codex_thread_id(transcript: Path) -> str | None:
    # rollout-<timestamp>-<thread uuid>.jsonl[.zst]
    stem = _source_key(transcript).removesuffix(".jsonl")
    try:
        return str(uuid.UUID(stem[-36:]))
    except ValueError:
        return None


def codex_spawned_threads(codex_home: Path) -> dict[str, list[str]]:
    """Parent thread id -> the thread ids it spawned, from Codex's own state database (read only)."""
    edges: dict[str, list[str]] = {}
    for database in sorted(codex_home.glob("state_*.sqlite")):
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5)
            try:
                rows = connection.execute("SELECT parent_thread_id, child_thread_id FROM thread_spawn_edges").fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            continue
        for parent, child in rows:
            edges.setdefault(parent, []).append(child)
    return edges


def _attach_codex_threads(units: list[HistoryUnit]) -> None:
    """Make every thread a Codex delete would take along a dependent of the deleted thread."""
    by_thread = {thread: unit.transcript for unit in units if (thread := codex_thread_id(unit.transcript))}
    edges: dict[Path, dict[str, list[str]]] = {}
    for unit in units:
        if unit.harness != "codex" or unit.codex_home is None:
            continue
        spawned = edges.setdefault(unit.codex_home, codex_spawned_threads(unit.codex_home))
        pending, seen = list(spawned.get(codex_thread_id(unit.transcript) or "", ())), set()
        while pending:
            child = pending.pop()
            if child in seen:
                continue
            seen.add(child)
            if child in by_thread:
                unit.dependents.append(by_thread[child])
            pending.extend(spawned.get(child, ()))


def keep_reason(
    unit: HistoryUnit,
    cursors: dict[str, ImportCursor],
    *,
    now: float,
    retention_days: float,
    exclude_globs: Iterable[str],
    open_files: set[str],
) -> str | None:
    """Why this unit must stay, or None when it may be deleted. This is the deletion guard."""
    globs = [pattern.lower() for pattern in exclude_globs if pattern]
    transcripts = [unit.transcript, *unit.dependents]
    cursor = cursors.get(_source_key(unit.transcript))
    # Threads Agent Hub linked as children; Codex's spawn edges already added the ones it knows.
    for child in cursor.children if cursor else ():
        if (child_path := _existing(child)) is not None and child_path not in transcripts:
            transcripts.append(child_path)
    labels = [str(path) for path in transcripts]
    for path in transcripts:
        if (path_cursor := cursors.get(_source_key(path))) is not None:
            labels.extend(path_cursor.labels)
    if any(fnmatch.fnmatchcase(value.lower(), pattern) for value in labels for pattern in globs):
        return "excluded"
    try:
        idle_days = (now - max(_latest_mtime(unit), *(path.stat().st_mtime for path in transcripts))) / 86400
    except OSError:
        return "unreadable"
    if idle_days < retention_days:
        return "recent"
    if any(os.path.realpath(path) in open_files for path in transcripts):
        return "open"
    for path in transcripts:
        path_cursor = cursors.get(_source_key(path))
        if path_cursor is None:
            return "not_in_agent_hub"
        if path_cursor.duplicate:
            return "duplicate_sessions"
        if not path_cursor.events_held:
            # Agent Hub's own event retention already dropped it: this file is the last full copy.
            return "events_not_held"
        if path_cursor.lossy:
            return "parse_issues"
        try:
            if not path_cursor.covers(path):
                return "not_fully_imported"
        except OSError:
            return "unreadable"
    return None


async def load_cursors(db: AsyncSession, paths: list[str]) -> dict[str, ImportCursor]:
    cursors: dict[str, ImportCursor] = {}
    transcript_path = Session.provider_metadata["transcript_path"].as_string()
    held = exists().where(SessionEvent.session_id == Session.id)
    for start in range(0, len(paths), 500):
        rows = (await db.execute(
            select(Session, held).where(transcript_path.in_(paths[start:start + 500]))
        )).all()
        parent_ids = [session.id for session, _ in rows if session.provider == "codex"]
        children: dict[str, list[str]] = {}
        if parent_ids:
            for parent_id, child_path in (await db.execute(
                select(Session.parent_session_id, transcript_path).where(Session.parent_session_id.in_(parent_ids))
            )).all():
                if child_path:
                    children.setdefault(parent_id, []).append(child_path)
        for session, events_held in rows:
            key = str(session.provider_metadata["transcript_path"])
            cursor = _cursor(session, events_held=bool(events_held), children=tuple(children.get(session.id, ())))
            if key in cursors or cursor is None:
                # Two sessions claim one file, or one without a byte cursor: never decide between them.
                previous = cursors.get(key) or cursor
                if previous is not None:
                    cursors[key] = ImportCursor(previous.session_id, None, None, -1, None, duplicate=key in cursors)
                continue
            cursors[key] = cursor
    return cursors


def _remove(unit: HistoryUnit, codex_bin: str) -> None:
    if unit.harness == "codex":
        thread_id = codex_thread_id(unit.transcript)
        if thread_id is None:
            raise RuntimeError(f"no thread id in {unit.transcript.name}")
        env = {**os.environ, **({"CODEX_HOME": str(unit.codex_home)} if unit.codex_home else {})}
        result = run_process(
            [codex_bin, "delete", "--force", thread_id],
            capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"codex delete {thread_id}: {(result.stderr or result.stdout).strip()[-300:]}")
        if unit.transcript.exists():
            raise RuntimeError(f"codex delete {thread_id} left {unit.transcript.name} in place")
        return
    for path in unit.paths():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def reclaim_sqlite(path: Path) -> int:
    """Return a database's free pages to the disk in short write locks; returns bytes freed."""
    connection = sqlite3.connect(path, timeout=5)
    try:
        if connection.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
            return 0  # only databases their owner created for incremental vacuum
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        free_pages = connection.execute("PRAGMA freelist_count").fetchone()[0]
        freed = 0
        # Bounded: pages a busy writer frees meanwhile wait for the next run.
        for _ in range(free_pages // _VACUUM_PAGES + 1):
            connection.execute(f"PRAGMA incremental_vacuum({_VACUUM_PAGES})").fetchall()
            connection.commit()
            remaining = connection.execute("PRAGMA freelist_count").fetchone()[0]
            freed += max(0, free_pages - remaining) * page_size
            free_pages = remaining
            if not remaining:
                break
        # The file shrinks once the WAL is checkpointed; Codex's own checkpoints finish it if readers block this one.
        connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()
    finally:
        connection.close()
    return freed


def _fingerprint(unit: HistoryUnit) -> tuple[float, int]:
    stat = unit.transcript.stat()
    return stat.st_mtime, stat.st_size


async def prune_local_history(
    db: AsyncSession,
    *,
    dry_run: bool = False,
    now: float | None = None,
    open_files: set[str] | None = None,
    remove: Callable[[HistoryUnit, str], None] = _remove,
) -> dict[str, Any]:
    """Delete idle, fully imported local transcripts; return per-harness counts."""
    retention_days = settings.local_history_retention_days
    if retention_days <= 0:
        return {}
    exclude = [pattern.strip() for pattern in settings.local_history_exclude_globs.split(",")]
    units = await asyncio.to_thread(_discover)
    await asyncio.to_thread(_attach_codex_threads, units)
    paths = list(dict.fromkeys(_source_key(path) for unit in units for path in (unit.transcript, *unit.dependents)))
    cursors = await load_cursors(db, paths)
    open_files = await asyncio.to_thread(open_paths) if open_files is None else open_files
    now = time.time() if now is None else now
    reports: dict[str, StoreReport] = {}
    for unit in units:
        report = reports.setdefault(unit.harness, StoreReport())
        if not unit.transcript.exists():
            report.kept["removed_with_parent"] += 1  # a Codex thread its parent's delete took along
            continue
        reason = await asyncio.to_thread(
            keep_reason, unit, cursors,
            now=now, retention_days=retention_days, exclude_globs=exclude, open_files=open_files,
        )
        if reason is None:
            try:
                fingerprint = await asyncio.to_thread(_fingerprint, unit)
                size = await asyncio.to_thread(_size, unit)
            except OSError:
                reason = "unreadable"
        if reason is not None:
            report.kept[reason] += 1
            continue
        if not dry_run:
            try:
                if await asyncio.to_thread(_fingerprint, unit) != fingerprint:
                    report.kept["changed_during_run"] += 1
                    continue
                await asyncio.to_thread(remove, unit, settings.local_history_codex_bin)
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                logger.warning("Local history: kept %s: %s", unit.transcript, exc)
                report.kept["delete_failed"] += 1
                continue
        report.deleted += 1
        report.freed_bytes += size
    result: dict[str, Any] = {harness: report.as_dict() for harness, report in reports.items()}
    if not dry_run and reports.get("codex", StoreReport()).deleted:
        reclaimed: dict[str, int] = {}
        for home in {unit.codex_home for unit in units if unit.codex_home is not None}:
            for database in sorted(home.glob("*.sqlite")):
                try:
                    reclaimed[database.name] = await asyncio.to_thread(reclaim_sqlite, database)
                except sqlite3.Error as exc:
                    logger.warning("Local history: could not reclaim %s: %s", database, exc)
        result["codex_sqlite_reclaimed_bytes"] = reclaimed
    return result


def _idle(path: Path, now: float, minutes: float) -> bool:
    try:
        return now - path.stat().st_mtime >= minutes * 60
    except OSError:
        return False


async def _ingest(db: AsyncSession, session: Session, path: Path) -> int:
    result = await ingest_transcript_events(
        db, session.id, TranscriptIngestRequest(provider="claude_code", transcript_path=str(path)), session=session,
    )
    return result.events_appended


def _subagent_meta(agent_file: Path) -> dict[str, Any]:
    try:
        meta = json.loads(agent_file.with_name(agent_file.stem + ".meta.json").read_text())
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


async def _record_subagent(db: AsyncSession, parent: Session, agent_file: Path, child_id: str) -> Session:
    parent_metadata = parent.provider_metadata if isinstance(parent.provider_metadata, dict) else {}
    meta = await asyncio.to_thread(_subagent_meta, agent_file)
    metadata = {
        "harness": "claude_code",
        "transcript_path": str(agent_file),
        "native_subagent_id": agent_file.stem,
        **{key: parent_metadata[key] for key in ("repo_root", "host") if parent_metadata.get(key)},
        **({"native_subagent_type": meta["agentType"]} if isinstance(meta.get("agentType"), str) else {}),
        **({"description": meta["description"]} if isinstance(meta.get("description"), str) else {}),
    }
    cwd = parent_metadata.get("cwd")
    model = await asyncio.to_thread(first_transcript_model, str(agent_file))
    child, _ = await upsert_session(db, SessionUpsertRequest(
        session_id=child_id,
        project_id=parent.project_id,
        provider=parent.provider,
        model=model or parent.model,
        session_type="claude_code",
        parent_session_id=parent.id,
        request_source="local-history",
        cwd=cwd if isinstance(cwd, str) else None,
        current_branch=parent.current_branch,
        provider_metadata=metadata,
    ))
    return child


def _idle_agent_files(sidecar: Path, now: float, minutes: float) -> list[Path]:
    return [path for path in sorted(sidecar.glob("subagents/**/agent-*.jsonl")) if _idle(path, now, minutes)]


async def _catch_up_subagents(db: AsyncSession, parent: Session, path: Path, now: float, counts: Counter[str]) -> None:
    sidecar = path.with_suffix("")
    for agent_file in await asyncio.to_thread(
        _idle_agent_files, sidecar, now, settings.local_history_catch_up_idle_minutes,
    ):
        child_id = subagent_session_id(parent.id, agent_file.relative_to(sidecar).as_posix())
        child = await db.get(Session, child_id)
        if child is None:
            child = await _record_subagent(db, parent, agent_file, child_id)
            counts["subagents_recorded"] += 1
        cursor = _cursor(child)
        never_imported = cursor is None and "transcript_ingestion" not in (child.provider_metadata or {})
        if never_imported or (cursor is not None and await asyncio.to_thread(_behind, cursor, agent_file)):
            counts["events_appended"] += await _ingest(db, child, agent_file)
        await close_session_if_active(db, child)


def _behind(cursor: ImportCursor, path: Path) -> bool:
    return cursor.same_source(path.stat()) and not cursor.covers(path)


def _parent_state(path: Path, cursor: ImportCursor | None) -> str:
    stat = path.stat()
    if cursor is None or not cursor.same_source(stat):
        return "source_changed"
    return "covered" if cursor.covers(path) else "behind"


async def catch_up_claude_code(db: AsyncSession, *, now: float | None = None) -> dict[str, int]:
    """Import what the Stop hook missed, and Claude Code subagent transcripts, for idle sessions."""
    now = time.time() if now is None else now
    roots = tuple(os.path.realpath(root) + os.sep for root in local_roots(claude_project_roots()))
    counts: Counter[str] = Counter()
    transcript_path = Session.provider_metadata["transcript_path"].as_string()
    parents = (await db.execute(
        select(Session.id, transcript_path).where(
            Session.session_type == "claude_code",
            Session.parent_session_id.is_(None),
            transcript_path.isnot(None),
        )
    )).all()
    for session_id, raw_path in parents:
        if not raw_path or not os.path.realpath(raw_path).startswith(roots):
            continue
        path = Path(raw_path)
        if not path.is_file():
            continue
        try:
            parent = await db.get(Session, session_id)
            if parent is None:
                continue
            if _idle(path, now, settings.local_history_catch_up_idle_minutes):
                state = await asyncio.to_thread(_parent_state, path, _cursor(parent))
                if state == "source_changed":
                    # A new device or inode would re-import the whole file under new identities.
                    counts["source_changed"] += 1
                elif state == "behind":
                    counts["events_appended"] += await _ingest(db, parent, path)
                    counts["caught_up"] += 1
            await _catch_up_subagents(db, parent, path, now, counts)
        except Exception as exc:  # one bad transcript must not stop the rest
            await db.rollback()
            logger.warning("Local history: catch-up failed for %s: %s", session_id, exc)
            counts["failed"] += 1
    return dict(counts)


async def run_local_history(db: AsyncSession, *, dry_run: bool = False) -> dict[str, Any]:
    caught_up = {} if dry_run else await catch_up_claude_code(db)
    return {"catch_up": caught_up, "pruned": await prune_local_history(db, dry_run=dry_run)}
