"""Parsing helpers for LLM session-analysis responses."""

from __future__ import annotations

from app.services.memory._summary_models import LLMAnalysisResult


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
    prefix_to_uuid: dict[str, str] = {}
    if memory_contents:
        prefix_to_uuid = {uuid[:8]: uuid for uuid in memory_contents}

    in_ratings = False
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("RATINGS:"):
            in_ratings = _handle_ratings_header(line, prefix_to_uuid, result)
            continue
        if in_ratings:
            if line.startswith("["):
                _parse_rating_line(line, prefix_to_uuid, result.ratings)
                continue
            in_ratings = False
        _apply_field(line, result, valid_outcomes, prefix_to_uuid)

    if not result.summary:
        result.summary = text[:200]
    return result


def _handle_ratings_header(
    line: str,
    prefix_to_uuid: dict[str, str],
    result: LLMAnalysisResult,
) -> bool:
    """Process the RATINGS: header line; returns whether in_ratings should be True."""
    val = line[len("RATINGS:"):].strip()
    if val.upper() == "NONE":
        return False
    if val.startswith("["):
        _parse_rating_line(val, prefix_to_uuid, result.ratings)
    return True


def _apply_field(
    line: str,
    result: LLMAnalysisResult,
    valid_outcomes: set[str],
    prefix_to_uuid: dict[str, str],
) -> None:
    """Apply a single non-ratings line to the result object."""
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


def create_fallback_summary(
    transcript: str,
    *,
    git_context: str | None = None,
) -> LLMAnalysisResult:
    """Return empty summary when LLM is unavailable.

    No summary is better than noise like "Session with N entries".
    The caller (summary_generator) treats empty summary as skipped.
    """
    return LLMAnalysisResult(summary="", tools=[], git_digest="")


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
