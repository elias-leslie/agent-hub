"""LLM-based summary generation for session summaries.

Uses Gemini to generate structured summaries from session transcripts,
with fallback to simple parsing if LLM is unavailable.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.constants import GEMINI_FLASH

logger = logging.getLogger(__name__)


async def generate_via_llm(
    session_id: str,
    project_id: str,
    agent_slug: str | None,
    transcript: str,
) -> tuple[str, list[str], list[str], list[str], list[str], str]:
    """Generate summary using Gemini via the google.genai SDK.

    Uses the same client pattern as the GeminiAdapter, calling
    client.aio.models.generate_content directly.

    Args:
        session_id: Session UUID for context.
        project_id: Project ID for context.
        agent_slug: Agent slug for context.
        transcript: Condensed session transcript.

    Returns:
        Tuple of (summary, key_decisions, tools_used, files_modified, topics, outcome).
    """
    default_template = """Summarize this AI coding session. Focus on discoveries, failure modes, and workarounds — not process narrative.

Session: {session_id}
Project: {project_id}
Agent: {agent_slug}

Transcript:
{transcript}

Respond in this EXACT format (no markdown, no extra text):
SUMMARY: <1-3 sentence summary focusing on what was accomplished or discovered, key failures, and workarounds found>
OUTCOME: <completed | failed | partial>
DECISIONS: <comma-separated list of key decisions made, or NONE>
TOOLS: <comma-separated list of unique tools used, or NONE>
FILES: <comma-separated list of files modified, or NONE>
TOPICS: <comma-separated list of topics/technologies, or NONE>"""

    from app.services.prompt_service import get_prompt_content

    template = await get_prompt_content("summary-generation", default_template)
    prompt = template.format(
        session_id=session_id,
        project_id=project_id,
        agent_slug=agent_slug or "unknown",
        transcript=transcript[:8000],
    )

    try:
        from google import genai
        from google.genai import types

        settings = get_settings()
        client = genai.Client(api_key=settings.gemini_api_key)

        response = await client.aio.models.generate_content(
            model=GEMINI_FLASH,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                temperature=0.3,
            ),
        )

        text = (response.text or "").strip()
        if not text:
            logger.warning("LLM returned empty response for session %s", session_id)
            return create_fallback_summary(transcript)

        return parse_summary_response(text)

    except Exception as e:
        logger.warning("LLM summary generation failed: %s", e)
        return create_fallback_summary(transcript)


def parse_summary_response(
    text: str,
) -> tuple[str, list[str], list[str], list[str], list[str], str]:
    """Parse structured LLM response into component fields.

    Args:
        text: Raw LLM response text.

    Returns:
        Tuple of (summary, decisions, tools, files, topics, outcome).
    """
    summary = ""
    outcome = "completed"
    decisions: list[str] = []
    tools: list[str] = []
    files: list[str] = []
    topics: list[str] = []

    valid_outcomes = {"completed", "failed", "partial", "abandoned"}

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("SUMMARY:"):
            summary = line[len("SUMMARY:") :].strip()
        elif line.startswith("OUTCOME:"):
            val = line[len("OUTCOME:") :].strip().lower()
            if val in valid_outcomes:
                outcome = val
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

    return summary, decisions, tools, files, topics, outcome


def create_fallback_summary(
    transcript: str,
) -> tuple[str, list[str], list[str], list[str], list[str], str]:
    """Generate basic summary when LLM is unavailable.

    Extracts tool names from the transcript and produces a minimal
    summary without requiring an LLM call.

    Args:
        transcript: Condensed session transcript.

    Returns:
        Tuple of (summary, decisions, tools, files, topics, outcome).
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

    return summary, [], tools[:10], [], [], "completed"
