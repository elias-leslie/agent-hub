"""The transcript a Pi, Codex or Claude Code step leaves on its attempt's child session.

Those harnesses write their own native JSONL (``StepResult.transcript_path``). When the attempt ends, this reads
that file with the same adapters interactive native sessions use and appends the result as ordinary
``session_events`` on the attempt session, so a step opened read-only shows what it did whatever ran it.

While the attempt runs, ``follow_attempt_transcript`` does the same for what the harness has finished writing so far,
from a cursor kept on the attempt (``provider_metadata["workflow_transcript"]``), so a running step's chat fills in
live and a worker crash keeps what was already read. The final ingest at the end reads the whole file again and
appends only what the live passes missed, so the rows are the ones a single end-of-attempt ingest would have written.

Idempotent: every native record carries a stable source identity, so running it again appends nothing. Cost is not
written here: the attempt's one ``cost_logs`` row set comes from ``usage.record_attempt_cost``; the per-message
usage on these events is for display only. A transcript that is missing or unreadable is reported as a plain note
for the attempt record and never fails the step.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.event_storage import storing_history
from app.services.session_ingestion._events import _adapter_for_provider
from app.services.session_ingestion.adapters.base import ProviderSessionRef
from app.services.session_ingestion.adapters.transcript_parsers import contained_transcript_path
from app.services.session_ingestion.models import AppendNormalizedEventsRequest
from app.services.session_ingestion.service import append_normalized_events

logger = logging.getLogger(__name__)

# The executors whose harness writes a native transcript (agent_hub writes its own, see agent_hub_transcript).
NATIVE_EXECUTORS = frozenset({"pi", "codex", "claude_code"})

# provider_metadata key on the attempt: {executor, path, native_session_id, checkpoint, events, at}.
CURSOR_KEY = "workflow_transcript"

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _note(events: int, skipped: int, note: str | None) -> dict[str, Any]:
    return {"events": events, "skipped": skipped, "note": note}


def _readable(transcript_path: str) -> str | None:
    """Why the transcript cannot be read, or None when it can (a plain sentence for the attempt record)."""

    path = contained_transcript_path(transcript_path)
    if path is None:
        return "transcript is outside the native transcript folders, so it was not read"
    if not path.is_file():
        return "transcript file is no longer on disk"
    return None


async def _read_events(
    executor: str, transcript_path: str, native_session_id: str | None, session_id: str,
    agent_slug: str | None, checkpoint: str | None,
) -> tuple[list[Any], str | None]:
    """The attempt session's events for the records after ``checkpoint`` (None: the whole file)."""

    adapter = _adapter_for_provider(executor)
    ref = ProviderSessionRef(provider_session_id=native_session_id or session_id, source_id=transcript_path)
    events, next_checkpoint = await adapter.read_new_events(ref, checkpoint)
    # Native records are keyed by source identity; the parser's own turn numbering must not collide with events
    # already on the session, so the database assigns the sequence (as for every native ingest).
    return [
        (event.model_copy(update={"sequence": None}) if event.source_event_id else event).model_copy(
            update={"agent_id": agent_slug, "agent_name": agent_slug} if agent_slug else {}
        )
        for event in events
    ], next_checkpoint


async def ingest_attempt_transcript(
    db: AsyncSession,
    session_id: str,
    *,
    executor: str | None,
    transcript_path: str | None,
    native_session_id: str | None,
    agent_slug: str | None = None,
) -> dict[str, Any] | None:
    """Append the attempt's native transcript as session events; returns ``{events, skipped, note}``.

    Reads the whole file, so it also appends whatever the live passes did not get to. None when the executor has no
    native transcript to read. Never raises: a failure comes back as the note.
    """

    if executor not in NATIVE_EXECUTORS:
        return None
    if not transcript_path:
        return _note(0, 0, "the harness recorded no transcript path, so the transcript is unknown")
    try:
        unreadable = await asyncio.to_thread(_readable, transcript_path)
        if unreadable:
            return _note(0, 0, unreadable)
        events, _ = await _read_events(executor, transcript_path, native_session_id, session_id, agent_slug, None)
        if not events:
            return _note(0, 0, "transcript held no records to show")
        # History, not activity: the attempt's activity times, live state and the run session stay as they are.
        with storing_history():
            result = await append_normalized_events(db, session_id, AppendNormalizedEventsRequest(events=events))
        return _note(result.events_appended, result.events_skipped, None)
    except Exception as exc:
        logger.warning("attempt %s: transcript %s not ingested", session_id, transcript_path, exc_info=True)
        await db.rollback()
        return _note(0, 0, f"transcript could not be read: {type(exc).__name__}: {str(exc)[:200]}")


async def follow_attempt_transcript(
    db: AsyncSession,
    session_id: str,
    *,
    executor: str | None,
    transcript_path: str | None,
    native_session_id: str | None,
    agent_slug: str | None = None,
) -> int:
    """While the attempt runs: append what the harness has finished writing since the last pass; returns events added.

    The cursor (parser checkpoint plus byte offset) lives on the attempt row and moves in the same transaction as the
    events, so a pass that fails or a worker that dies leaves events and cursor together. A last line the harness is
    still writing is not read until it ends with its newline. Same history rules as the final ingest: no activity,
    no cost rows, no copies on the run session. Never raises; a transcript that is not there yet is simply nothing yet.
    """

    if executor not in NATIVE_EXECUTORS or not transcript_path:
        return 0
    try:
        if await asyncio.to_thread(_readable, transcript_path):
            return 0
        attempt = await db.get(Session, session_id, with_for_update=True, populate_existing=True)
        if attempt is None:
            return 0
        meta = dict(attempt.provider_metadata or {})
        cursor: dict[str, Any] = meta.get(CURSOR_KEY) or {}
        checkpoint = cursor.get("checkpoint") if cursor.get("path") == transcript_path else None
        events, next_checkpoint = await _read_events(
            executor, transcript_path, native_session_id, session_id, agent_slug, checkpoint
        )
        appended = 0
        if events:
            with storing_history():
                result = await append_normalized_events(
                    db, session_id, AppendNormalizedEventsRequest(events=events), commit=False
                )
            appended = result.events_appended
        if next_checkpoint != checkpoint or appended:
            meta[CURSOR_KEY] = {
                "executor": executor,
                "path": transcript_path,
                "native_session_id": native_session_id,
                "checkpoint": next_checkpoint,
                "events": int(cursor.get("events") or 0) + appended if checkpoint else appended,
            }
            attempt.provider_metadata = meta
        await db.commit()
        return appended
    except Exception as exc:
        # The first line of a Pi file or a transcript being created can be unreadable for a moment; the next pass retries.
        log = logger.debug if isinstance(exc, ValueError) else logger.warning
        log("attempt %s: live transcript pass skipped (%s: %s)", session_id, type(exc).__name__, str(exc)[:200])
        await db.rollback()
        return 0


async def ingest_attempt_in_own_session(
    factory: SessionFactory,
    session_id: str,
    *,
    executor: str | None,
    transcript_path: str | None,
    native_session_id: str | None,
    agent_slug: str | None = None,
) -> dict[str, Any] | None:
    """``ingest_attempt_transcript`` in a short transaction of its own (the engine holds none across an executor)."""

    if executor not in NATIVE_EXECUTORS:
        return None
    try:
        async with factory() as db:
            return await ingest_attempt_transcript(
                db,
                session_id,
                executor=executor,
                transcript_path=transcript_path,
                native_session_id=native_session_id,
                agent_slug=agent_slug,
            )
    except Exception as exc:
        logger.warning("attempt %s: transcript ingest failed", session_id, exc_info=True)
        return _note(0, 0, f"transcript could not be stored: {type(exc).__name__}: {str(exc)[:200]}")
