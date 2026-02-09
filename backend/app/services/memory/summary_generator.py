"""Session summary auto-generation for the Agent Hub memory dashboard.

Generates AI-powered summaries of completed sessions, extracting key decisions,
tools used, files modified, and topics. Stores the summary as an episode in the
knowledge graph for future retrieval.

Usage:
    from app.services.memory.summary_generator import generate_session_summary

    summary = await generate_session_summary("session-uuid-here")
    print(summary.summary)
    print(summary.key_decisions)
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select

from app.db import _get_session_factory
from app.models import Session, SessionEvent
from app.services.memory.summary_llm import generate_via_llm
from app.services.memory.summary_storage import store_as_episode
from app.services.memory.summary_transcript import build_condensed_transcript


class SessionSummary(BaseModel):
    """Result of session summary generation."""

    session_id: str
    summary: str
    key_decisions: list[str]
    tools_used: list[str]
    files_modified: list[str]
    topics: list[str]
    generated_at: str
    episode_uuid: str | None = None


async def generate_session_summary(
    session_id: str,
    project_id: str | None = None,
) -> SessionSummary:
    """Generate an AI summary for a completed session.

    Fetches session events from PostgreSQL, builds a condensed transcript,
    calls Gemini to generate a structured summary, and stores the result
    as an episode in the knowledge graph.

    Args:
        session_id: The UUID of the session to summarize.
        project_id: Optional project_id fallback (for race conditions
            where session was just registered).

    Returns:
        SessionSummary with structured summary data.

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

    # 2. Build condensed transcript from events
    transcript = build_condensed_transcript(events)

    # 3. Generate summary using Gemini
    summary_text, key_decisions, tools_used, files_modified, topics = (
        await generate_via_llm(
            session_id=session_id,
            project_id=effective_project_id,
            agent_slug=session.agent_slug,
            transcript=transcript,
        )
    )

    # 4. Store as episode in memory system
    episode_uuid = await store_as_episode(
        session_id, effective_project_id, summary_text
    )

    return SessionSummary(
        session_id=session_id,
        summary=summary_text,
        key_decisions=key_decisions,
        tools_used=tools_used,
        files_modified=files_modified,
        topics=topics,
        generated_at=datetime.now(UTC).isoformat(),
        episode_uuid=episode_uuid,
    )
