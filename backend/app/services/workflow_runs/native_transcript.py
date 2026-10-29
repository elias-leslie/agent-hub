"""The transcript a Pi, Codex or Claude Code step leaves on its attempt's child session.

Those harnesses write their own native JSONL (``StepResult.transcript_path``). When the attempt ends, this reads
that file with the same adapters interactive native sessions use and appends the result as ordinary
``session_events`` on the attempt session, so a step opened read-only shows what it did whatever ran it.

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

from app.services.event_storage import storing_history
from app.services.session_ingestion._events import _adapter_for_provider
from app.services.session_ingestion.adapters.base import ProviderSessionRef
from app.services.session_ingestion.adapters.transcript_parsers import contained_transcript_path
from app.services.session_ingestion.models import AppendNormalizedEventsRequest
from app.services.session_ingestion.service import append_normalized_events

logger = logging.getLogger(__name__)

# The executors whose harness writes a native transcript (agent_hub writes its own, see agent_hub_transcript).
NATIVE_EXECUTORS = frozenset({"pi", "codex", "claude_code"})

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

    None when the executor has no native transcript to read. Never raises: a failure comes back as the note.
    """

    if executor not in NATIVE_EXECUTORS:
        return None
    if not transcript_path:
        return _note(0, 0, "the harness recorded no transcript path, so the transcript is unknown")
    try:
        unreadable = await asyncio.to_thread(_readable, transcript_path)
        if unreadable:
            return _note(0, 0, unreadable)
        adapter = _adapter_for_provider(executor)
        ref = ProviderSessionRef(provider_session_id=native_session_id or session_id, source_id=transcript_path)
        events, _ = await adapter.read_new_events(ref, None)
        if not events:
            return _note(0, 0, "transcript held no records to show")
        # Native records are keyed by source identity; the parser's own turn numbering must not collide with events
        # already on the session, so the database assigns the sequence (as for every native ingest).
        events = [
            (event.model_copy(update={"sequence": None}) if event.source_event_id else event).model_copy(
                update={"agent_id": agent_slug, "agent_name": agent_slug} if agent_slug else {}
            )
            for event in events
        ]
        # History, not activity: the attempt's activity times, live state and the run session stay as they are.
        with storing_history():
            result = await append_normalized_events(db, session_id, AppendNormalizedEventsRequest(events=events))
        return _note(result.events_appended, result.events_skipped, None)
    except Exception as exc:
        logger.warning("attempt %s: transcript %s not ingested", session_id, transcript_path, exc_info=True)
        await db.rollback()
        return _note(0, 0, f"transcript could not be read: {type(exc).__name__}: {str(exc)[:200]}")


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
