"""Ingest finished Pi, Codex and Claude Code workflow attempts' native transcripts as session events.

New attempts are ingested by the engine when they end (``workflow_runs.native_transcript``); this catches up the
attempts that finished before that. Ingested events are history: no session's activity time moves. Safe to run again: events already stored are skipped, and an attempt whose
transcript file is gone gets a plain note instead.
Run with: python -m scripts.backfill_workflow_transcripts [--dry-run] [--run RUN_ID_PREFIX]
"""

import argparse
import asyncio
import logging
from collections import Counter
from typing import Any

from sqlalchemy import select, update

from app.db import async_session
from app.models import Session
from app.services.workflow_runs.native_transcript import NATIVE_EXECUTORS, ingest_attempt_transcript

logging.basicConfig(level=logging.WARNING)


async def backfill(dry_run: bool, run_prefix: str | None) -> Counter[str]:
    totals: Counter[str] = Counter()
    async with async_session() as db:
        rows = (
            await db.execute(
                select(Session.id, Session.parent_session_id, Session.agent_slug, Session.provider_metadata)
                .where(Session.request_source == "workflow_run", Session.parent_session_id.is_not(None))
                .order_by(Session.created_at)
            )
        ).all()
    for attempt_id, run_id, agent_slug, metadata in rows:
        detail: dict[str, Any] = (metadata or {}).get("workflow_attempt") or {}
        executor = detail.get("executor")
        if executor not in NATIVE_EXECUTORS or (run_prefix and not str(run_id).startswith(run_prefix)):
            continue
        totals["attempts"] += 1
        totals[f"{executor}_attempts"] += 1
        if dry_run:
            continue
        async with async_session() as db:
            done = await ingest_attempt_transcript(
                db,
                attempt_id,
                executor=executor,
                transcript_path=detail.get("transcript_path"),
                native_session_id=detail.get("native_session_id"),
                agent_slug=agent_slug,
            )
            assert done is not None
            # The note is history too: updated_at is named in the statement so the column's on-update stamp stays off.
            meta = {**(metadata or {}), "workflow_attempt": {**detail, "transcript": done}}
            await db.execute(
                update(Session).where(Session.id == attempt_id).values(provider_metadata=meta, updated_at=Session.updated_at)
            )
            await db.commit()
        totals["events_appended"] += done["events"]
        totals["events_already_there"] += done["skipped"]
        totals["with_events" if done["events"] or done["skipped"] else "with_note_only"] += 1
        totals[f"{executor}_events"] += done["events"]
    return totals


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="count the attempts that would be read, change nothing")
    parser.add_argument("--run", help="only attempts of the run whose id starts with this")
    args = parser.parse_args()
    for name, value in sorted(asyncio.run(backfill(args.dry_run, args.run)).items()):
        print(f"{name}: {value}")


if __name__ == "__main__":
    main()
