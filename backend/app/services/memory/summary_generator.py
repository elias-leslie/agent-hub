"""Session summary auto-generation for the Agent Hub memory dashboard.

Generates AI-powered summaries of completed sessions, extracting key decisions,
tools used, files modified, and topics. Stores the summary on the Session row
in PostgreSQL for efficient continuity injection.

Usage:
    from app.services.memory.summary_generator import generate_session_summary

    summary = await generate_session_summary("session-uuid-here")
    print(summary.summary)
    print(summary.key_decisions)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select

from app.db import _get_session_factory
from app.models import Session, SessionEvent, SessionSummarySegment
from app.services.memory.summary_llm import LLMAnalysisResult, generate_via_llm
from app.services.memory.summary_transcript import build_condensed_transcript

logger = logging.getLogger(__name__)

# Minimum transcript lines required to generate a meaningful summary.
# Set to 20 to skip low-signal sessions: CC sessions with only memory events,
# git-agent (~3 events), reviewer (~3 events), triager (~3 events).
# Coder (~27 avg) and refactor (~34 avg) sessions pass this threshold.
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
    """Generate an AI summary for a completed session.

    Fetches session events from PostgreSQL, builds a condensed transcript,
    calls Gemini to generate a structured summary, and stores the result
    on the Session row in PostgreSQL.

    Includes a quality gate: if the transcript has fewer than
    MIN_TRANSCRIPT_LINES meaningful lines, the summary is skipped
    (no LLM call, no storage).

    Args:
        session_id: The UUID of the session to summarize.
        project_id: Optional project_id fallback (for race conditions
            where session was just registered).
        git_context: Raw ``git log --oneline`` captured by Stop.sh.
        memory_contents: Loaded memory UUIDs→content for combined rating.

    Returns:
        SessionSummary with structured summary data. If skipped,
        ``skipped=True``.

    Raises:
        ValueError: If session not found or has no events.
    """
    # 1. Fetch session + events from PostgreSQL
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

    effective_project_id = session.project_id or project_id or "unknown"

    # 2. Build condensed transcript — prefer CC JSONL (richer) over session events (sparse)
    transcript = ""
    if transcript_path:
        from app.services.memory.summary_transcript import build_transcript_from_cc_jsonl

        transcript = build_transcript_from_cc_jsonl(transcript_path)
        if transcript:
            logger.info("Using CC JSONL transcript for session %s", session_id)

    if not transcript:
        transcript = build_condensed_transcript(events)

    # 3. Quality gate: skip if transcript too thin
    transcript_lines = len(transcript.strip().split("\n")) if transcript.strip() else 0
    if transcript_lines < MIN_TRANSCRIPT_LINES:
        logger.info(
            "Skipping summary for session %s: insufficient transcript (%d lines, need %d)",
            session_id,
            transcript_lines,
            MIN_TRANSCRIPT_LINES,
        )
        return SessionSummary(
            session_id=session_id,
            summary=f"Insufficient transcript ({transcript_lines} lines)",
            key_decisions=[],
            tools_used=[],
            files_modified=[],
            topics=[],
            generated_at=datetime.now(UTC).isoformat(),
            skipped=True,
        )

    # 4. Generate summary + ratings using Gemini (single call)
    analysis: LLMAnalysisResult = await generate_via_llm(
        session_id=session_id,
        project_id=effective_project_id,
        agent_slug=session.agent_slug,
        transcript=transcript,
        git_context=git_context,
        memory_contents=memory_contents,
    )

    # 5. Store summary on Session row in PostgreSQL (cap git_digest at 500 chars)
    git_digest = analysis.git_digest[:500] if analysis.git_digest else ""
    await _store_summary_on_session(
        session_id=session_id,
        summary_oneliner=analysis.summary,
        outcome=analysis.outcome,
        files_touched=analysis.files,
        branch=branch,
        is_worktree=is_worktree,
        git_digest=git_digest,
    )

    return SessionSummary(
        session_id=session_id,
        summary=analysis.summary,
        outcome=analysis.outcome,
        key_decisions=analysis.decisions,
        tools_used=analysis.tools,
        files_modified=analysis.files,
        topics=analysis.topics,
        git_digest=analysis.git_digest,
        ratings=analysis.ratings,
        generated_at=datetime.now(UTC).isoformat(),
    )


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

    Updates the session columns (backward compat) and creates a new
    SessionSummarySegment row so that resumed sessions accumulate
    multiple summary entries instead of overwriting a single one.
    """
    session_factory = _get_session_factory()
    async with session_factory() as db:
        result = await db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            logger.warning("Session %s not found for summary storage", session_id)
            return

        # Update session columns (backward compat for pre-segment consumers)
        session.summary_oneliner = summary_oneliner
        session.summary_outcome = outcome
        session.summary_files_touched = files_touched if files_touched else None
        session.summary_generated_at = datetime.now(UTC)
        session.summary_branch = branch
        session.summary_is_worktree = is_worktree
        session.summary_git_digest = git_digest or None

        # Append a segment row for incremental history
        segment = SessionSummarySegment(
            session_id=session_id,
            summary_oneliner=summary_oneliner,
            summary_outcome=outcome,
            summary_git_digest=git_digest or None,
            summary_branch=branch,
            summary_is_worktree=is_worktree,
        )
        db.add(segment)
        await db.commit()

    logger.info(
        "Stored summary + segment on session %s: outcome=%s branch=%s worktree=%s files=%d git_digest=%s",
        session_id,
        outcome,
        branch,
        is_worktree,
        len(files_touched),
        bool(git_digest),
    )
