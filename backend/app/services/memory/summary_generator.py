"""
Session summary auto-generation for the Agent Hub memory dashboard.

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

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.constants import GEMINI_FLASH
from app.db import _get_session_factory
from app.models import Session, SessionEvent

logger = logging.getLogger(__name__)


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
        session_result = await db.execute(select(Session).where(Session.id == session_id))
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
    transcript = _build_condensed_transcript(events)

    # 3. Generate summary using Gemini
    summary_text, key_decisions, tools_used, files_modified, topics = await _generate_via_llm(
        session_id=session_id,
        project_id=effective_project_id,
        agent_slug=session.agent_slug,
        transcript=transcript,
    )

    # 4. Store as episode in memory system
    episode_uuid = await _store_as_episode(session_id, effective_project_id, summary_text)

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


def _build_condensed_transcript(events: Sequence[Any]) -> str:
    """Build a condensed transcript from session events for summarization.

    Extracts user messages, assistant messages, tool calls, and errors
    into a compact format. Truncates individual entries and limits total
    output to the last 100 lines.
    """
    lines: list[str] = []
    for event in events:
        if event.event_type == "user_message" and event.content:
            lines.append(f"USER: {event.content[:500]}")
        elif event.event_type == "assistant_message" and event.content:
            lines.append(f"ASSISTANT: {event.content[:500]}")
        elif event.event_type == "tool_use" and event.tool_name:
            input_preview = ""
            if event.tool_input:
                input_str = str(event.tool_input)
                input_preview = f" ({input_str[:100]})"
            lines.append(f"TOOL: {event.tool_name}{input_preview}")
        elif event.event_type == "tool_result" and event.tool_output:
            output_str = str(event.tool_output)
            lines.append(f"RESULT: {output_str[:200]}")
        elif event.event_type == "error" and event.content:
            lines.append(f"ERROR: {event.content[:200]}")

    # Return last 100 lines max to keep within token budget
    return "\n".join(lines[-100:])


async def _generate_via_llm(
    session_id: str,
    project_id: str,
    agent_slug: str | None,
    transcript: str,
) -> tuple[str, list[str], list[str], list[str], list[str]]:
    """Generate summary using Gemini via the google.genai SDK.

    Uses the same client pattern as the GeminiAdapter, calling
    client.aio.models.generate_content directly.

    Returns:
        Tuple of (summary, key_decisions, tools_used, files_modified, topics).
    """
    prompt = f"""Summarize this AI coding session. Return a structured summary.

Session: {session_id}
Project: {project_id}
Agent: {agent_slug or "unknown"}

Transcript:
{transcript[:8000]}

Respond in this EXACT format (no markdown, no extra text):
SUMMARY: <1-3 sentence summary of what was accomplished>
DECISIONS: <comma-separated list of key decisions made, or NONE>
TOOLS: <comma-separated list of unique tools used, or NONE>
FILES: <comma-separated list of files modified, or NONE>
TOPICS: <comma-separated list of topics/technologies, or NONE>"""

    try:
        from google import genai
        from google.genai import types

        settings = get_settings()
        client = genai.Client(api_key=settings.gemini_api_key)

        response = await client.aio.models.generate_content(
            model=GEMINI_FLASH,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                max_output_tokens=500,
                temperature=0.3,
            ),
        )

        text = (response.text or "").strip()
        if not text:
            logger.warning("LLM returned empty response for session %s", session_id)
            return _fallback_summary(transcript)

        return _parse_summary_response(text)

    except Exception as e:
        logger.warning("LLM summary generation failed: %s", e)
        return _fallback_summary(transcript)


def _parse_summary_response(
    text: str,
) -> tuple[str, list[str], list[str], list[str], list[str]]:
    """Parse structured LLM response into component fields."""
    summary = ""
    decisions: list[str] = []
    tools: list[str] = []
    files: list[str] = []
    topics: list[str] = []

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("SUMMARY:"):
            summary = line[len("SUMMARY:") :].strip()
        elif line.startswith("DECISIONS:"):
            val = line[len("DECISIONS:") :].strip()
            if val.upper() != "NONE":
                decisions = [d.strip() for d in val.split(",") if d.strip()]
        elif line.startswith("TOOLS:"):
            val = line[len("TOOLS:") :].strip()
            if val.upper() != "NONE":
                tools = [t.strip() for t in val.split(",") if t.strip()]
        elif line.startswith("FILES:"):
            val = line[len("FILES:") :].strip()
            if val.upper() != "NONE":
                files = [f.strip() for f in val.split(",") if f.strip()]
        elif line.startswith("TOPICS:"):
            val = line[len("TOPICS:") :].strip()
            if val.upper() != "NONE":
                topics = [t.strip() for t in val.split(",") if t.strip()]

    if not summary:
        summary = text[:200]

    return summary, decisions, tools, files, topics


def _fallback_summary(
    transcript: str,
) -> tuple[str, list[str], list[str], list[str], list[str]]:
    """Generate basic summary when LLM is unavailable.

    Extracts tool names from the transcript and produces a minimal
    summary without requiring an LLM call.
    """
    tools: list[str] = []

    for line in transcript.split("\n"):
        if line.startswith("TOOL: "):
            tool_name = line[len("TOOL: ") :].split("(")[0].strip()
            if tool_name and tool_name not in tools:
                tools.append(tool_name)

    line_count = len(transcript.split("\n"))
    summary = f"Session with {line_count} transcript entries"
    if tools:
        summary += f", used tools: {', '.join(tools[:5])}"

    return summary, [], tools[:10], [], []


async def _store_as_episode(
    session_id: str,
    project_id: str,
    summary_text: str,
) -> str | None:
    """Store session summary as a memory episode in the knowledge graph.

    Uses the EpisodeCreator single-funnel pattern with the LEARNING
    ingestion profile (reference tier, 5min dedup window).

    Returns:
        The episode UUID if stored successfully, None otherwise.
    """
    try:
        from graphiti_core.utils.datetime_utils import utc_now

        from app.services.memory.episode_creator import get_episode_creator
        from app.services.memory.ingestion_config import LEARNING
        from app.services.memory.memory_models import MemoryScope

        creator = get_episode_creator(scope=MemoryScope.GLOBAL)
        result = await creator.create(
            content=f"[Session Summary: {session_id}]\n{summary_text}",
            name=f"session_summary_{session_id}_{utc_now().isoformat()}",
            config=LEARNING,
            source_description=f"session_summary session:{session_id} project:{project_id}",
            reference_time=utc_now(),
        )
        return result.uuid if result.success else None
    except Exception as e:
        logger.error("Failed to store session summary as episode: %s", e)
        return None
