"""LLM-based summary generation for session summaries.

Uses Gemini to generate structured summaries from session transcripts,
with fallback to simple parsing if LLM is unavailable.

The ``session-analysis`` prompt slug produces summary + memory ratings in
a single LLM call, replacing the previous two-call approach (separate
``summary-generation`` and hardcoded rater prompt).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import get_settings
from app.constants import GEMINI_FLASH

logger = logging.getLogger(__name__)


@dataclass
class LLMAnalysisResult:
    """Combined result from the single session-analysis LLM call."""

    summary: str = ""
    outcome: str = "completed"
    decisions: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    git_digest: str = ""
    ratings: dict[str, str] = field(default_factory=dict)


# Combined prompt template — produces summary + ratings in one call.
_DEFAULT_SESSION_ANALYSIS_TEMPLATE = """\
Analyze this AI coding session. Focus on discoveries, failure modes, and workarounds — not process narrative.
If the transcript spans multiple work periods (separated by "--- [recent work below] ---"), prioritize the MOST RECENT work in the summary. The transcript is chronological — the end reflects the latest activity.

Session: {session_id}
Project: {project_id}
Agent: {agent_slug}

Transcript:
{transcript}
{git_context_block}
{memory_block}
Respond in this EXACT format (no markdown, no extra text):
SUMMARY: <1-3 sentence summary focusing on what was accomplished or discovered, key failures, and workarounds found>
OUTCOME: <completed | failed | partial>
DECISIONS: <comma-separated list of key decisions made, or NONE>
TOOLS: <comma-separated list of unique tools used, or NONE>
FILES: <comma-separated list of files modified, or NONE>
TOPICS: <comma-separated list of topics/technologies, or NONE>
GIT_DIGEST: <1-line digest of commits relevant to this session, or NONE>
RATINGS: <one "[uuid8] helpful|harmful|neutral" per line, or NONE if no memories listed above>"""


async def generate_via_llm(
    session_id: str,
    project_id: str,
    agent_slug: str | None,
    transcript: str,
    *,
    git_context: str | None = None,
    memory_contents: dict[str, str] | None = None,
) -> LLMAnalysisResult:
    """Generate summary + memory ratings using Gemini in a single call.

    Args:
        session_id: Session UUID for context.
        project_id: Project ID for context.
        agent_slug: Agent slug for context.
        transcript: Condensed session transcript.
        git_context: Raw ``git log --oneline`` output captured by Stop.sh.
        memory_contents: Dict of ``{full_uuid: content}`` for loaded memories.

    Returns:
        LLMAnalysisResult with all parsed fields.
    """
    from app.services.prompt_service import get_prompt_content

    # Build optional blocks — validate git_context before passing to LLM
    git_context_block = ""
    if git_context and git_context.strip():
        git_context_block = f"\nGit commits during session:\n{git_context.strip()}\n"

    memory_block = ""
    if memory_contents:
        lines = [
            f"[{uuid[:8]}] {content[:200]}"
            for uuid, content in memory_contents.items()
        ]
        memory_block = "\nMemories loaded into session:\n" + "\n".join(lines) + "\n"

    # Try the new combined slug first, fall back to legacy slug
    template = await get_prompt_content(
        "session-analysis", _DEFAULT_SESSION_ANALYSIS_TEMPLATE
    )

    prompt = template.format(
        session_id=session_id,
        project_id=project_id,
        agent_slug=agent_slug or "unknown",
        transcript=transcript[:8000],
        git_context_block=git_context_block,
        memory_block=memory_block,
    )

    try:
        from google import genai
        from google.genai import types

        from app.services.credential_manager import get_credential_manager

        settings = get_settings()
        cm = get_credential_manager()
        api_key = cm.get_api_key("gemini") if cm.is_initialized else None
        client = genai.Client(api_key=api_key or settings.gemini_api_key)

        response = await client.aio.models.generate_content(
            model=GEMINI_FLASH,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(temperature=0.3),
        )

        text = (response.text or "").strip()
        if not text:
            logger.warning("LLM returned empty response for session %s", session_id)
            return create_fallback_summary(transcript, git_context=git_context)

        return parse_summary_response(text, memory_contents=memory_contents)

    except Exception as e:
        logger.warning("LLM summary generation failed: %s", e)
        return create_fallback_summary(transcript, git_context=git_context)


def parse_summary_response(
    text: str,
    *,
    memory_contents: dict[str, str] | None = None,
) -> LLMAnalysisResult:
    """Parse structured LLM response into component fields.

    Handles both the legacy 6-field format and the new extended format
    with GIT_DIGEST and RATINGS lines.
    """
    result = LLMAnalysisResult()
    valid_outcomes = {"completed", "failed", "partial", "abandoned"}

    # Build prefix→full UUID map for rating resolution
    prefix_to_uuid: dict[str, str] = {}
    if memory_contents:
        prefix_to_uuid = {uuid[:8]: uuid for uuid in memory_contents}

    in_ratings = False

    for line in text.split("\n"):
        line = line.strip()

        # Once we see RATINGS:, subsequent [uuid] lines are rating entries
        if line.startswith("RATINGS:"):
            val = line[len("RATINGS:"):].strip()
            if val.upper() == "NONE":
                in_ratings = False
                continue
            in_ratings = True
            # The value after RATINGS: might be the first rating line
            if val.startswith("["):
                _parse_rating_line(val, prefix_to_uuid, result.ratings)
            continue

        if in_ratings:
            if line.startswith("["):
                _parse_rating_line(line, prefix_to_uuid, result.ratings)
                continue
            # End of ratings block on any non-rating line
            in_ratings = False

        if line.startswith("SUMMARY:"):
            result.summary = line[len("SUMMARY:"):].strip()
        elif line.startswith("OUTCOME:"):
            val = line[len("OUTCOME:"):].strip().lower()
            if val in valid_outcomes:
                result.outcome = val
        elif line.startswith("DECISIONS:"):
            result.decisions = _parse_csv(line[len("DECISIONS:"):])
        elif line.startswith("TOOLS:"):
            result.tools = _parse_csv(line[len("TOOLS:"):])
        elif line.startswith("FILES:"):
            result.files = _parse_csv(line[len("FILES:"):])
        elif line.startswith("TOPICS:"):
            result.topics = _parse_csv(line[len("TOPICS:"):])
        elif line.startswith("GIT_DIGEST:"):
            val = line[len("GIT_DIGEST:"):].strip()
            if val.upper() != "NONE":
                result.git_digest = val[:500]

    if not result.summary:
        result.summary = text[:200]

    return result


def create_fallback_summary(
    transcript: str,
    *,
    git_context: str | None = None,
) -> LLMAnalysisResult:
    """Generate basic summary when LLM is unavailable.

    When git_context is provided, includes commit subjects in the summary
    so even fallbacks carry useful information.
    """
    tools: list[str] = []

    for line in transcript.split("\n"):
        if line.startswith("TOOL: "):
            tool_name = line[len("TOOL: "):].split("(")[0].strip()
            if tool_name and tool_name not in tools:
                tools.append(tool_name)

    line_count = len(transcript.split("\n"))

    # Build summary line
    parts = [f"Session with {line_count} entries"]
    if tools:
        parts.append(f"({', '.join(tools[:5])})")

    # Extract first commit subject from git context for fallback enrichment
    git_digest = ""
    if git_context:
        commit_lines = [
            ln.strip() for ln in git_context.strip().split("\n") if ln.strip()
        ]
        if commit_lines:
            # Take first 3 commit subjects (strip hash prefix if present)
            subjects = []
            for cl in commit_lines[:3]:
                # git log --oneline: "abc1234 commit msg"
                if " " in cl:
                    subjects.append(cl.split(" ", 1)[1])
                else:
                    subjects.append(cl)
            git_digest = "; ".join(subjects)[:500]
            parts.append(f"Commits: {subjects[0]}")

    summary = " ".join(parts) if len(parts) <= 2 else ". ".join(parts)

    return LLMAnalysisResult(
        summary=summary,
        tools=tools[:10],
        git_digest=git_digest,
    )


# ── Helpers ──────────────────────────────────────────────────────────────


def _parse_csv(raw: str) -> list[str]:
    """Parse a comma-separated value string, returning empty list for NONE."""
    val = raw.strip()
    if val.upper() == "NONE":
        return []
    return [item.strip() for item in val.split(",") if item.strip()]


def _parse_rating_line(
    line: str,
    prefix_to_uuid: dict[str, str],
    ratings: dict[str, str],
) -> None:
    """Parse a single ``[uuid8] helpful|harmful|neutral`` line into *ratings*."""
    valid_ratings = {"helpful", "harmful", "neutral"}
    bracket_end = line.find("]")
    if bracket_end < 0:
        return
    prefix = line[1:bracket_end].strip()
    rating = line[bracket_end + 1:].strip().lower()
    if rating in valid_ratings and prefix in prefix_to_uuid:
        ratings[prefix_to_uuid[prefix]] = rating
