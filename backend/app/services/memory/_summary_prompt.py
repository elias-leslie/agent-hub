"""Prompt template and builder for session-analysis LLM calls."""

from __future__ import annotations

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


def build_git_context_block(git_context: str | None) -> str:
    """Return formatted git context block or empty string."""
    if git_context and git_context.strip():
        return f"\nGit commits during session:\n{git_context.strip()}\n"
    return ""


def build_memory_block(memory_contents: dict[str, str] | None) -> str:
    """Return formatted memory block or empty string."""
    if not memory_contents:
        return ""
    lines = [
        f"[{uuid[:8]}] {content[:200]}"
        for uuid, content in memory_contents.items()
    ]
    return "\nMemories loaded into session:\n" + "\n".join(lines) + "\n"


async def build_prompt(
    session_id: str,
    project_id: str,
    agent_slug: str | None,
    transcript: str,
    *,
    git_context: str | None = None,
    memory_contents: dict[str, str] | None = None,
) -> str:
    """Build the session-analysis prompt string."""
    from app.services.prompt_service import get_prompt_content

    template = await get_prompt_content(
        "session-analysis", _DEFAULT_SESSION_ANALYSIS_TEMPLATE
    )
    return template.format(
        session_id=session_id,
        project_id=project_id,
        agent_slug=agent_slug or "unknown",
        transcript=transcript[:8000],
        git_context_block=build_git_context_block(git_context),
        memory_block=build_memory_block(memory_contents),
    )
