"""Compact old finished sessions' events into one compressed archive per session.

A finished session idle longer than ``settings.session_events_archive_after_days`` keeps its events as one
xz-compressed JSONL row in ``session_event_archives`` (``row_to_json`` of each event, in turn/sequence
order) and its raw rows are deleted. ``title`` and ``summary`` keep what the session list and the detail
header read without the events. Readers merge archived events back in (``session_events_with_archive``,
``load_archived_events``); a write to an archived session first restores its rows
(``restore_archived_events``), so callers see the same events either way.

xz, not pglz or lz4: on a 300-session sample the rows took 703 MB in the table and 88 MB as xz JSONL
(zlib -9: 167 MB); lz4 TOAST came out 6% larger than the default pglz.
"""

from __future__ import annotations

import asyncio
import json
import logging
import lzma
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy import DateTime, bindparam, exists, func, select, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Session, SessionEvent, SessionEventArchive, SessionEventType

logger = logging.getLogger(__name__)

ARCHIVE_FORMAT = "jsonl+xz"
_XZ_PRESET = 6
_FINISHED_STATUSES = ("completed", "failed")
_STREAM_ROWS = 500

_ROWS_SQL = text(
    "SELECT se.id::text, row_to_json(se)::text FROM session_events se "
    "WHERE se.session_id = :session_id ORDER BY se.turn, se.sequence, se.created_at, se.id"
)


@dataclass(frozen=True)
class ArchiveSummary:
    title: str | None
    event_count: int
    summary: dict[str, Any]


@dataclass(frozen=True)
class ArchivedSession:
    session_id: str
    event_count: int
    raw_bytes: int
    stored_bytes: int


@dataclass
class CompactionResult:
    sessions: int = 0
    events: int = 0
    raw_bytes: int = 0
    stored_bytes: int = 0
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


async def lock_session_events(db: AsyncSession, session_id: str) -> None:
    """The per-session ingestion lock (event_storage.lock_session_event_ingestion takes the same key)."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"session-events:{session_id}"},
    )


@lru_cache
def _event_columns() -> tuple[tuple[str, str, bool], ...]:
    """(column name, mapped attribute key, is timestamp) for every SessionEvent column."""
    return tuple(
        (prop.columns[0].name, prop.key, isinstance(prop.columns[0].type, DateTime))
        for prop in sa_inspect(SessionEvent).column_attrs
    )


def _event_from_record(record: dict[str, Any]) -> SessionEvent:
    """A transient (never added) SessionEvent from one archived ``row_to_json`` record."""
    values: dict[str, Any] = {}
    for name, key, is_time in _event_columns():
        if name not in record:
            continue
        value = record[name]
        if is_time and isinstance(value, str):
            value = datetime.fromisoformat(value)
            if value.tzinfo is not None:
                value = value.astimezone(UTC)  # row_to_json writes the server's offset; rows read back in UTC
        values[key] = value
    return SessionEvent(**values)


def decode_archive(archive_format: str, payload: bytes) -> list[dict[str, Any]]:
    if archive_format != ARCHIVE_FORMAT:
        raise ValueError(f"Unknown session event archive format: {archive_format}")
    return [json.loads(line) for line in lzma.decompress(payload).split(b"\n") if line]


def _decode_events(archive_format: str, payload: bytes) -> list[SessionEvent]:
    return [_event_from_record(record) for record in decode_archive(archive_format, payload)]


async def has_archive(db: AsyncSession, session_id: str) -> bool:
    found = await db.execute(select(exists().where(SessionEventArchive.session_id == session_id)))
    return found.scalar() is True


async def fetch_archive_summaries(db: AsyncSession, session_ids: Sequence[str]) -> dict[str, ArchiveSummary]:
    """Title, event count and summary per archived session (never the payload)."""
    if not session_ids:
        return {}
    rows = await db.execute(
        select(
            SessionEventArchive.session_id,
            SessionEventArchive.title,
            SessionEventArchive.event_count,
            SessionEventArchive.summary,
        ).where(SessionEventArchive.session_id.in_(list(session_ids)))
    )
    return {
        str(session_id): ArchiveSummary(title=title, event_count=int(count), summary=summary or {})
        for session_id, title, count, summary in rows
    }


async def load_archived_events(db: AsyncSession, session_id: str) -> list[SessionEvent]:
    """The session's archived events as transient objects, in stored order; [] when not archived."""
    row = (
        await db.execute(
            select(SessionEventArchive.format, SessionEventArchive.payload).where(
                SessionEventArchive.session_id == session_id
            )
        )
    ).first()
    if row is None:
        return []
    return await asyncio.to_thread(_decode_events, row[0], row[1])


def _event_order(event: SessionEvent) -> tuple[Any, ...]:
    return (event.turn, event.sequence, event.created_at, str(event.id))


async def merge_archived_events(
    db: AsyncSession, session_id: str, rows: Sequence[SessionEvent]
) -> list[SessionEvent]:
    """Archived events plus live rows (rows win on a shared id), in (turn, sequence) order."""
    archived = await load_archived_events(db, session_id)
    if not archived:
        return sorted(rows, key=_event_order)
    return await asyncio.to_thread(_merge_events, archived, rows)


def _merge_events(archived: list[SessionEvent], rows: Sequence[SessionEvent]) -> list[SessionEvent]:
    row_ids = {str(event.id) for event in rows}
    merged = [event for event in archived if str(event.id) not in row_ids]
    merged.extend(rows)
    return sorted(merged, key=_event_order)


async def session_events_with_archive(db: AsyncSession, session: Session) -> list[SessionEvent]:
    """All of a session's events (``session.events`` must be loaded), archived ones included."""
    return await merge_archived_events(db, session.id, list(session.events))


async def restore_archived_events(db: AsyncSession, session_id: str) -> int:
    """Put an archived session's events back into rows before something writes to it.

    Takes the ingestion lock only when there is an archive. All or nothing: when any archived event's
    id, turn/sequence or source event id is already taken by a live row, no row is restored and the
    archive stays (reads still merge it), so nothing is lost or counted twice. Returns the rows restored.
    """
    if not await has_archive(db, session_id):
        return 0
    await lock_session_events(db, session_id)
    return await _restore_locked(db, session_id)


async def _restore_locked(db: AsyncSession, session_id: str) -> int:
    archive = await db.get(SessionEventArchive, session_id, populate_existing=True)
    if archive is None:
        return 0
    records = await asyncio.to_thread(decode_archive, archive.format, archive.payload)
    restored = 0
    if records:
        known = {name for name, _key, _is_time in _event_columns()}
        cols = ", ".join(f'"{name}"' for name in records[0] if name in known)
        rows_json = await asyncio.to_thread(json.dumps, records)
        savepoint = await db.begin_nested()
        result = await db.execute(
            text(
                f"INSERT INTO session_events ({cols}) SELECT {cols} "
                "FROM json_populate_recordset(NULL::session_events, CAST(:rows AS json)) "
                "ON CONFLICT DO NOTHING RETURNING id"
            ),
            {"rows": rows_json},
        )
        restored = len(result.all())
        if restored < len(records):
            await savepoint.rollback()
            logger.warning(
                "Session %s: %d of %d archived events collide with live rows; the archive stays as it is",
                session_id, len(records) - restored, len(records),
            )
            return 0
        await savepoint.commit()
    await db.delete(archive)
    await db.flush()
    return restored


async def _summarize(db: AsyncSession, session_id: str) -> tuple[str | None, dict[str, Any]]:
    """What the list and detail header read, computed from the session's rows by the live queries."""
    from app.services.session_queries import (
        _HARNESS_SCAFFOLD_PATTERN,
        _TITLE_SOURCE_PREFIX_CHARS,
        fetch_native_usage_rollups,
        fetch_session_agent_token_aggregates,
        fetch_session_event_type_counts,
        fetch_session_statistics,
        fetch_session_titles,
    )

    by_type = await fetch_session_event_type_counts(db, session_id)
    _messages, _events, token_stats, _children, _active = await fetch_session_statistics(db, [session_id])
    usage = (await fetch_native_usage_rollups(db, [session_id])).get(session_id)
    agents = await fetch_session_agent_token_aggregates(db, session_id)
    # The list's prompt search reads these prefixes (session_queries._prompt_match).
    prompts = await db.execute(
        select(func.left(SessionEvent.content, _TITLE_SOURCE_PREFIX_CHARS))
        .where(
            SessionEvent.session_id == session_id,
            SessionEvent.event_type == SessionEventType.USER_MESSAGE,
            ~SessionEvent.content.op("~*")(_HARNESS_SCAFFOLD_PATTERN),
        )
        .order_by(SessionEvent.turn, SessionEvent.sequence)
    )
    summary = {
        "by_type": by_type,
        "tokens": token_stats.get(session_id),
        "usage": None if usage is None else asdict(usage),
        "agents": [asdict(agent) for agent in agents],
        "prompts": [prompt for prompt in prompts.scalars() if prompt],
    }
    return (await fetch_session_titles(db, [session_id])).get(session_id), summary


async def archive_session_events(
    db: AsyncSession, session_id: str, *, idle_before: datetime | None = None
) -> ArchivedSession | None:
    """Move one session's event rows into its archive, merging an earlier archive. The caller commits.

    With ``idle_before``, the session must still be finished and idle since then once the lock is held.
    Returns None when there is nothing to archive, the session no longer qualifies, or an earlier
    archive could not be restored (the session is left as it was).
    """
    await lock_session_events(db, session_id)
    if idle_before is not None and not await _still_archivable(db, session_id, idle_before):
        return None
    if await has_archive(db, session_id):
        await _restore_locked(db, session_id)
        if await has_archive(db, session_id):
            return None
    title, summary = await _summarize(db, session_id)
    times = (
        await db.execute(
            text("SELECT min(created_at), max(created_at) FROM session_events WHERE session_id = :sid"),
            {"sid": session_id},
        )
    ).one()

    compressor = lzma.LZMACompressor(preset=_XZ_PRESET)
    chunks: list[bytes] = []
    ids: list[str] = []
    raw_bytes = 0
    stream = await db.stream(_ROWS_SQL, {"session_id": session_id})
    async for partition in stream.partitions(_STREAM_ROWS):
        ids.extend(row[0] for row in partition)
        data = "".join(row[1] + "\n" for row in partition).encode()
        raw_bytes += len(data)
        chunks.append(await asyncio.to_thread(compressor.compress, data))
    if not ids:
        return None
    chunks.append(compressor.flush())
    payload = b"".join(chunks)

    db.add(
        SessionEventArchive(
            session_id=session_id,
            format=ARCHIVE_FORMAT,
            payload=payload,
            event_count=len(ids),
            raw_bytes=raw_bytes,
            title=title,
            summary=summary,
            first_event_at=times[0],
            last_event_at=times[1],
        )
    )
    await db.flush()
    # Only the archived ids: a row a lock-free writer added meanwhile stays a row and reads merge it.
    # One array parameter: a long session has more ids than a statement may have parameters.
    await db.execute(
        text("DELETE FROM session_events WHERE session_id = :session_id AND id = ANY(CAST(:ids AS uuid[]))"),
        {"session_id": session_id, "ids": ids},
    )
    return ArchivedSession(session_id, len(ids), raw_bytes, len(payload))


_ARCHIVABLE_SQL = """
    s.status::text IN :statuses AND COALESCE(s.last_activity_at, s.updated_at) < :cutoff
"""


async def _still_archivable(db: AsyncSession, session_id: str, idle_before: datetime) -> bool:
    found = await db.execute(
        text(f"SELECT 1 FROM sessions s WHERE s.id = :session_id AND {_ARCHIVABLE_SQL}").bindparams(
            bindparam("statuses", expanding=True)
        ),
        {"session_id": session_id, "statuses": list(_FINISHED_STATUSES), "cutoff": idle_before},
    )
    return found.first() is not None


async def archivable_session_ids(db: AsyncSession, cutoff: datetime) -> list[str]:
    """Finished sessions idle since before ``cutoff`` that still have event rows, oldest first."""
    rows = await db.execute(
        text(
            f"""
            SELECT s.id FROM sessions s
            WHERE {_ARCHIVABLE_SQL}
              AND EXISTS (SELECT 1 FROM session_events e WHERE e.session_id = s.id)
            ORDER BY COALESCE(s.last_activity_at, s.updated_at), s.id
            """
        ).bindparams(bindparam("statuses", expanding=True)),
        {"statuses": list(_FINISHED_STATUSES), "cutoff": cutoff},
    )
    return [str(session_id) for session_id in rows.scalars()]


async def compact_old_sessions(db: AsyncSession, older_than_days: float) -> CompactionResult:
    """Archive every finished session idle past the window, one transaction per session."""
    result = CompactionResult()
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    for session_id in await archivable_session_ids(db, cutoff):
        await db.commit()
        try:
            archived = await archive_session_events(db, session_id, idle_before=cutoff)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Session %s: event archive failed; its rows are unchanged", session_id)
            result.failed.append(session_id)
            continue
        if archived is None:
            result.skipped.append(session_id)
            continue
        result.sessions += 1
        result.events += archived.event_count
        result.raw_bytes += archived.raw_bytes
        result.stored_bytes += archived.stored_bytes
    return result


async def vacuum_session_events(db: AsyncSession) -> None:
    """Plain VACUUM so archived rows' space is reused (and a free tail returned) without locking writers."""
    bind = db.bind
    if not isinstance(bind, AsyncEngine):
        raise TypeError("VACUUM needs a connection of its own; the session must be bound to an engine")
    async with bind.connect() as conn:
        autocommit = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text("VACUUM (ANALYZE) session_events"))
