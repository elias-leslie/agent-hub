"""Session summary auto-generation for the Agent Hub memory dashboard.

Usage:
    from app.services.memory.summary_generator import generate_session_summary
    summary = await generate_session_summary("session-uuid-here")
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select

from app.db import _get_session_factory
from app.models import Session, SessionEvent, SessionSummarySegment
from app.services.memory.summary_llm import LLMAnalysisResult, generate_via_llm
from app.services.memory.summary_transcript import build_condensed_transcript

logger = logging.getLogger(__name__)

# Minimum transcript lines to generate a meaningful summary (20 skips low-signal
# sessions: CC/git-agent/reviewer/triager; coder ~27, refactor ~34 pass).
MIN_TRANSCRIPT_LINES = 20


class SessionSummary(BaseModel):
    """Result of session summary generation."""

    session_id: str
    summary: str
    outcome: str = "completed"
    key_decisions: list[str]
    tools_used: list[str]
    files_modified: list[str]
    topics: list[str]
    git_digest: str = ""
    ratings: dict[str, str] = {}
    generated_at: str
    skipped: bool = False


def _build_transcript(session_id: str, events: Sequence[SessionEvent], transcript_path: str | None) -> str:
    """Return condensed transcript, preferring CC JSONL over session events."""
    if transcript_path:
        from app.services.memory.summary_transcript import build_transcript_from_cc_jsonl

        cc = build_transcript_from_cc_jsonl(transcript_path)
        if cc:
            logger.info("Using CC JSONL transcript for session %s", session_id)
            return cc
    return build_condensed_transcript(events)


async def _fetch_session_and_events(session_id: str) -> tuple[Session, Sequence[SessionEvent]]:
    """Fetch session and ordered events from PostgreSQL."""
    async with _get_session_factory()() as db:
        row = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()
        if not row:
            raise ValueError(f"Session {session_id} not found")
        events = (
            await db.execute(
                select(SessionEvent)
                .where(SessionEvent.session_id == session_id)
                .order_by(SessionEvent.turn, SessionEvent.sequence)
                .limit(200)
            )
        ).scalars().all()
    if not events:
        raise ValueError(f"Session {session_id} has no events")
    return row, events


async def _store_summary_on_session(
    session_id: str,
    summary_oneliner: str,
    outcome: str,
    files_touched: list[str],
    branch: str | None = None,
    is_worktree: bool = False,
    git_digest: str = "",
) -> None:
    """Persist structured summary on Session row and append a summary segment."""
    async with _get_session_factory()() as db:
        session = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one_or_none()
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
            session_id=session_id, summary_oneliner=summary_oneliner,
            summary_outcome=outcome, summary_git_digest=git_digest or None,
            summary_branch=branch, summary_is_worktree=is_worktree,
        ))
        await db.commit()
    logger.info(
        "Stored summary + segment on session %s: outcome=%s branch=%s worktree=%s files=%d git_digest=%s",
        session_id, outcome, branch, is_worktree, len(files_touched), bool(git_digest),
    )


def _enforce_oneliner(summary: str, max_chars: int = 150) -> str:
    """Enforce summary_oneliner length limit."""
    if len(summary) <= max_chars:
        return summary
    # Try to truncate at last sentence boundary under limit
    truncated = summary[:max_chars]
    last_period = truncated.rfind('. ')
    if last_period > max_chars // 2:  # Only if we keep at least half
        return truncated[:last_period + 1]
    return truncated[:max_chars - 3].rstrip() + "..."


async def generate_session_summary(
    session_id: str,
    project_id: str | None = None,
    branch: str | None = None,
    is_worktree: bool = False,
    transcript_path: str | None = None,
    *,
    git_context: str | None = None,
    memory_contents: dict[str, str] | None = None,
) -> SessionSummary:
    """Generate an AI summary for a completed session. Raises ValueError if not found."""
    session, events = await _fetch_session_and_events(session_id)
    transcript = _build_transcript(session_id, events, transcript_path)
    n_lines = len(transcript.strip().split("\n")) if transcript.strip() else 0
    if n_lines < MIN_TRANSCRIPT_LINES:
        logger.info(
            "Skipping summary for session %s: insufficient transcript (%d lines, need %d)",
            session_id, n_lines, MIN_TRANSCRIPT_LINES,
        )
        return SessionSummary(
            session_id=session_id, summary=f"Insufficient transcript ({n_lines} lines)",
            key_decisions=[], tools_used=[], files_modified=[], topics=[],
            generated_at=datetime.now(UTC).isoformat(), skipped=True,
        )
    analysis: LLMAnalysisResult = await generate_via_llm(
        session_id=session_id, project_id=session.project_id or project_id or "unknown",
        agent_slug=session.agent_slug, transcript=transcript,
        git_context=git_context, memory_contents=memory_contents,
    )
    analysis.summary = _enforce_oneliner(analysis.summary)

    # Empty summary = fallback fired, skip storage (no summary > noise summary)
    if not analysis.summary:
        logger.info("Skipping summary storage for session %s: empty summary (fallback)", session_id)
        return SessionSummary(
            session_id=session_id, summary="",
            key_decisions=[], tools_used=[], files_modified=[], topics=[],
            generated_at=datetime.now(UTC).isoformat(), skipped=True,
        )

    git_digest = analysis.git_digest[:500] if analysis.git_digest else ""
    await _store_summary_on_session(
        session_id=session_id, summary_oneliner=analysis.summary, outcome=analysis.outcome,
        files_touched=analysis.files, branch=branch, is_worktree=is_worktree, git_digest=git_digest,
    )
    return SessionSummary(
        session_id=session_id, summary=analysis.summary, outcome=analysis.outcome,
        key_decisions=analysis.decisions, tools_used=analysis.tools, files_modified=analysis.files,
        topics=analysis.topics, git_digest=analysis.git_digest, ratings=analysis.ratings,
        generated_at=datetime.now(UTC).isoformat(),
    )
