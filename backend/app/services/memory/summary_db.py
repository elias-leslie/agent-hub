"""PostgreSQL persistence helpers for session summaries."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select

from app.db import _get_session_factory
from app.models import Session, SessionEvent, SessionSummarySegment

logger = logging.getLogger(__name__)


async def fetch_session_and_events(
    session_id: str,
) -> tuple[Session, Sequence[SessionEvent]]:
    """Fetch session and ordered events from PostgreSQL."""
    session_factory = _get_session_factory()
    async with session_factory() as db:
        session_result = await db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = session_result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Session {session_id} not found")

        events_result = await db.execute(
            select(SessionEvent)
            .where(SessionEvent.session_id == session_id)
            .order_by(SessionEvent.turn, SessionEvent.sequence)
            .limit(200)
        )
        events = events_result.scalars().all()

    if not events:
        raise ValueError(f"Session {session_id} has no events")
    return session, events


async def _store_summary_on_session(
    session_id: str,
    summary_oneliner: str,
    outcome: str,
    files_touched: list[str],
    branch: str | None = None,
    is_worktree: bool = False,
    git_digest: str = "",
) -> None:
    """Persist structured summary on Session row and append a summary segment.

    Updates session columns (backward compat) and creates a new
    SessionSummarySegment row so resumed sessions accumulate history.
    """
    session_factory = _get_session_factory()
    async with session_factory() as db:
        result = await db.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if not session:
            logger.warning("Session %s not found for summary storage", session_id)
            return

        session.summary_oneliner = summary_oneliner
        session.summary_outcome = outcome
        session.summary_files_touched = files_touched if files_touched else None
        session.summary_generated_at = datetime.now(UTC)
        session.summary_branch = branch
        session.summary_is_worktree = is_worktree
        session.summary_git_digest = git_digest or None

        db.add(SessionSummarySegment(
            session_id=session_id,
            summary_oneliner=summary_oneliner,
            summary_outcome=outcome,
            summary_git_digest=git_digest or None,
            summary_branch=branch,
            summary_is_worktree=is_worktree,
        ))
        await db.commit()

    logger.info(
        "Stored summary + segment on session %s: outcome=%s branch=%s worktree=%s files=%d git_digest=%s",
        session_id, outcome, branch, is_worktree, len(files_touched), bool(git_digest),
    )
