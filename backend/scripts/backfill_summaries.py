#!/usr/bin/env python
"""One-time backfill: generate summaries for sessions that were closed before
_dispatch_summary_on_close() existed (added 2026-02-16).

These sessions have 20+ events but no summary_oneliner. Dispatches Hatchet
summary tasks with a 2s throttle to avoid overwhelming the Gemini API.

Usage:
    cd backend && .venv/bin/python scripts/backfill_summaries.py [--dry-run]
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import and_, func, select

# Bootstrap the app so db + hatchet are available
sys.path.insert(0, ".")

from app.db import _get_session_factory  # noqa: E402
from app.models import Session, SessionEvent  # noqa: E402


async def find_eligible_sessions() -> list[tuple[str, str | None, str | None, bool]]:
    """Find completed sessions with 20+ events and no summary."""
    session_factory = _get_session_factory()
    async with session_factory() as db:
        subq = (
            select(
                SessionEvent.session_id,
                func.count(SessionEvent.id).label("cnt"),
            )
            .group_by(SessionEvent.session_id)
            .having(func.count(SessionEvent.id) >= 20)
            .subquery()
        )
        query = (
            select(
                Session.id,
                Session.current_branch,
                Session.summary_branch,
                Session.summary_is_worktree,
                subq.c.cnt,
            )
            .join(subq, Session.id == subq.c.session_id)
            .where(
                and_(
                    Session.summary_oneliner.is_(None),
                    Session.status == "completed",
                )
            )
            .order_by(subq.c.cnt.desc())
        )
        result = await db.execute(query)
        return [
            (row.id, row.current_branch, row.summary_branch, row.summary_is_worktree or False)
            for row in result.all()
        ]


async def main() -> None:
    dry_run = "--dry-run" in sys.argv

    sessions = await find_eligible_sessions()
    print(f"Found {len(sessions)} sessions eligible for backfill")

    if not sessions:
        return

    if dry_run:
        for sid, cb, sb, iw in sessions:
            branch = cb or sb or "main"
            print(f"  [DRY-RUN] {sid} branch={branch} worktree={iw}")
        return

    # Lazy import to avoid Hatchet init in dry-run mode
    from app.workflows.summary import SummaryInput, session_summary_task

    for i, (sid, cb, sb, iw) in enumerate(sessions):
        branch = cb or sb or "main"
        try:
            await session_summary_task.aio_run_no_wait(
                input=SummaryInput(
                    session_id=sid,
                    branch=branch,
                    is_worktree=iw,
                ),
            )
            print(f"  [{i + 1}/{len(sessions)}] Dispatched: {sid} branch={branch}")
        except Exception as e:
            print(f"  [{i + 1}/{len(sessions)}] FAILED: {sid}: {e}")

        # Gentle throttle — Gemini API rate limits
        await asyncio.sleep(2)

    print(f"\nDone. Dispatched {len(sessions)} summary tasks.")
    print("Monitor: journalctl --user -u agent-hub-hatchet-worker -f | grep summary")


if __name__ == "__main__":
    asyncio.run(main())
