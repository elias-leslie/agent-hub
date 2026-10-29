"""Undo the activity side effects of the first workflow transcript backfill.

That run stored its events the way a live session stores them: every attempt and run session got a new
``last_activity_at``/``updated_at`` and live state, and each tool/answer event was mirrored onto the run session as a
``child_session_update``. Ingested events are history, not activity (``event_storage.storing_history``), so this puts
it back, for the attempts that have events ingested inside the window:

- the mirrored ``child_session_update``/``child_session_blocked`` events the window added to their run sessions are
  deleted (they are copies of the attempt's own events);
- each attempt's and run's ``last_activity_at`` and ``updated_at`` return to the real end time (the attempt's
  ``finished_at``, else its latest event outside the window, else ``created_at``; a run: its latest remaining event or
  attempt end), and live state and ``models_used`` to what the engine had written when the attempt ended;
- attempts whose note was the only write get their ``updated_at`` back.

Run with: python -m scripts.repair_backfilled_transcript_activity [--dry-run] --since ISO --until ISO
"""

import argparse
import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update

from app.db import async_session
from app.models import Session, SessionEvent
from app.services.workflow_runs.native_transcript import NATIVE_EXECUTORS

MIRRORED = ("child_session_update", "child_session_blocked")


def _utc(epoch: Any) -> datetime | None:
    return datetime.fromtimestamp(float(epoch), UTC) if isinstance(epoch, int | float) else None


def _restored_live(current: dict[str, Any] | None, at: datetime, summary: str | None, completed: bool) -> dict[str, Any]:
    """The attempt's live state as the engine left it: its workflow block, plus the terminal fields when it completed."""

    live: dict[str, Any] = {k: v for k, v in (current or {}).items() if k == "workflow"}
    if completed:
        stamp = at.isoformat()
        live.update(
            {
                "phase": "completed", "status": "completed", "summary": summary,
                "termination_reason": "workflow_attempt_completed", "stall_reason": None,
                "current_tool_name": None, "current_topic": None, "outstanding_tool_calls": 0,
                "last_event_at": stamp, "last_model_activity_at": stamp,
            }
        )
    return live


async def repair(dry_run: bool, since: datetime, until: datetime) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    async with async_session() as db:
        in_window = SessionEvent.created_at.between(since, until)
        ingested = (
            await db.execute(
                select(SessionEvent.session_id).where(in_window, SessionEvent.source_event_id.is_not(None)).distinct()
            )
        ).scalars().all()
        attempts = [
            a
            for a in (await db.execute(select(Session).where(Session.id.in_(ingested)))).scalars()
            if ((a.provider_metadata or {}).get("workflow_attempt") or {}).get("executor") in NATIVE_EXECUTORS
        ]
        runs: dict[str, list[Session]] = {}
        for attempt in attempts:
            if attempt.parent_session_id:
                runs.setdefault(attempt.parent_session_id, []).append(attempt)
        attempt_ids = [a.id for a in attempts]

        mirrored = (
            select(SessionEvent.id)
            .where(
                in_window,
                SessionEvent.event_type.in_(MIRRORED),
                SessionEvent.session_id.in_(list(runs)),
                SessionEvent.tool_output["child_session_id"].as_string().in_(attempt_ids),
            )
        )
        n_mirrored = (await db.execute(select(func.count()).select_from(mirrored.subquery()))).scalar_one()
        if not dry_run:
            await db.execute(delete(SessionEvent).where(SessionEvent.id.in_(mirrored)))

        for attempt in attempts:
            detail = (attempt.provider_metadata or {}).get("workflow_attempt") or {}
            latest = (
                await db.execute(
                    select(func.max(SessionEvent.created_at)).where(
                        SessionEvent.session_id == attempt.id, ~in_window
                    )
                )
            ).scalar_one()
            end = _utc(detail.get("finished_at")) or latest or attempt.created_at
            meta = dict(attempt.provider_metadata or {})
            completed = attempt.status == "completed"
            meta["live_activity"] = _restored_live(meta.get("live_activity"), end, attempt.summary_oneliner, completed)
            served = [m for m in dict.fromkeys(detail.get("served_models") or []) if m]
            values: dict[str, Any] = {
                "last_activity_at": end, "updated_at": end, "provider_metadata": meta,
                **({"models_used": served} if served else {}),
            }
            report.append(
                {"id": attempt.id, "kind": "attempt", "before": attempt.last_activity_at, "after": end}
            )
            if not dry_run:
                await db.execute(update(Session).where(Session.id == attempt.id).values(**values))

        for run_id, children in runs.items():
            run = await db.get(Session, run_id)
            if run is None:
                continue
            remaining = (
                await db.execute(
                    select(SessionEvent.created_at, SessionEvent.event_type)
                    .where(SessionEvent.session_id == run_id, ~SessionEvent.id.in_(mirrored))
                    .order_by(SessionEvent.created_at.desc())
                    .limit(1)
                )
            ).first()
            ends = [t for t in (remaining[0] if remaining else None, *(
                _utc(((c.provider_metadata or {}).get("workflow_attempt") or {}).get("finished_at")) for c in children
            )) if t]
            end = max(ends) if ends else run.created_at
            meta = dict(run.provider_metadata or {})
            live = dict(meta.get("live_activity") or {})
            live.update({"last_event_at": end.isoformat(), **({"last_event_type": remaining[1]} if remaining else {})})
            meta["live_activity"] = live
            report.append({"id": run_id, "kind": "run", "before": run.last_activity_at, "after": end})
            if not dry_run:
                await db.execute(
                    update(Session).where(Session.id == run_id).values(
                        last_activity_at=end, updated_at=end, provider_metadata=meta
                    )
                )
        # Attempts with no transcript on disk only got their note written: updated_at alone moved.
        stamped = (
            Session.request_source == "workflow_run",
            Session.updated_at.between(since, until),
            Session.last_activity_at < since,
        )
        noted = (await db.execute(select(func.count()).select_from(Session).where(*stamped))).scalar_one()
        if not dry_run:
            await db.execute(update(Session).where(*stamped).values(updated_at=Session.last_activity_at))
            await db.commit()
    print(f"note-only attempts with updated_at put back: {noted}")
    print(f"attempts: {len(attempts)}  runs: {len(runs)}  mirrored events {'to delete' if dry_run else 'deleted'}: {n_mirrored}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since", required=True, help="start of the backfill window (ISO, with timezone)")
    parser.add_argument("--until", required=True, help="end of the backfill window (ISO, with timezone)")
    args = parser.parse_args()
    report = asyncio.run(repair(args.dry_run, datetime.fromisoformat(args.since), datetime.fromisoformat(args.until)))
    for row in report[:4] + report[-2:]:
        print(f"{row['kind']} {row['id'][:8]}: last_activity_at {row['before']} -> {row['after']}")


if __name__ == "__main__":
    main()
