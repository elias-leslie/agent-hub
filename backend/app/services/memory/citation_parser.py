"""Citation parser for extracting rule IDs from LLM responses.

Parses [M:uuid8], [G:uuid8], [R:uuid8] citations and inline [[F:...]] / [[S:...]] tags.
Data models and regex patterns live in _citation_types.py; this module contains logic.
"""

import logging
import re

from ._citation_types import (
    CITATION_PATTERN,
    FEEDBACK_TAG_PATTERN,
    FEEDBACK_TAG_PATTERN_LEGACY,
    SUMMARY_TAG_PATTERN,
    VALID_FEEDBACK_TYPES,
    VALID_SUMMARY_OUTCOMES,
    Citation,
    CitationType,
    FeedbackParseResult,
    FeedbackTag,
    ParseResult,
    SummaryParseResult,
    SummaryTag,
)

__all__ = [
    "Citation", "CitationType", "FeedbackParseResult", "FeedbackTag",
    "ParseResult", "SummaryParseResult", "SummaryTag",
    "extract_feedback_tags", "extract_summary_tags", "extract_uuid_prefixes",
    "format_citation", "format_guardrail_citation", "format_mandate_citation",
    "format_reference_citation", "parse_citations", "parse_feedback_tags",
    "parse_summary_tags", "resolve_full_uuids",
]

logger = logging.getLogger(__name__)


def parse_citations(response_text: str) -> ParseResult:
    """Parse [M:uuid8], [G:uuid8], [R:uuid8] citations from an LLM response."""
    if not response_text:
        return ParseResult(citations=[], unique_uuids=[])

    citations: list[Citation] = []
    seen_uuids: set[str] = set()
    mandate_count = guardrail_count = reference_count = 0

    for match in CITATION_PATTERN.finditer(response_text):
        ctype_str = match.group(1).upper()
        uuid_prefix = match.group(2).lower()
        try:
            ctype = CitationType(ctype_str)
        except ValueError:
            logger.warning("Unknown citation type: %s", ctype_str)
            continue

        citations.append(Citation(type=ctype, uuid_prefix=uuid_prefix))
        seen_uuids.add(uuid_prefix)
        if ctype == CitationType.MANDATE:
            mandate_count += 1
        elif ctype == CitationType.GUARDRAIL:
            guardrail_count += 1
        else:
            reference_count += 1

    logger.debug(
        "Parsed %d citations (%d mandates, %d guardrails, %d references) from response",
        len(citations), mandate_count, guardrail_count, reference_count,
    )
    return ParseResult(
        citations=citations,
        mandate_count=mandate_count,
        guardrail_count=guardrail_count,
        reference_count=reference_count,
        unique_uuids=list(seen_uuids),
    )


def extract_uuid_prefixes(response_text: str) -> list[str]:
    """Extract unique UUID prefixes from citations in response text."""
    return parse_citations(response_text).unique_uuids


async def _resolve_prefix(repo: object, prefix: str, group_id: str) -> str | None:
    """Resolve a single UUID prefix, trying global scope as fallback."""
    try:
        return await repo.resolve_uuid_prefix(prefix, group_id=group_id)  # type: ignore[attr-defined]
    except ValueError:
        pass
    if group_id == "global":
        logger.debug("Could not resolve UUID prefix: %s", prefix)
        return None
    try:
        return await repo.resolve_uuid_prefix(prefix, group_id="global")  # type: ignore[attr-defined]
    except ValueError:
        logger.debug("Could not resolve UUID prefix: %s", prefix)
        return None


async def resolve_full_uuids(
    uuid_prefixes: list[str],
    group_id: str = "global",
) -> dict[str, str]:
    """Resolve 8-char UUID prefixes to full UUIDs from PostgreSQL."""
    if not uuid_prefixes:
        return {}

    from .repository import get_memory_repository

    repo = get_memory_repository()
    result: dict[str, str] = {}
    for prefix in uuid_prefixes:
        full_uuid = await _resolve_prefix(repo, prefix, group_id)
        if full_uuid is not None:
            result[prefix] = full_uuid

    logger.debug("Resolved %d/%d UUID prefixes", len(result), len(uuid_prefixes))
    return result


def format_citation(uuid: str, citation_type: CitationType) -> str:
    """Format a UUID into a citation string like [M:abc12345]."""
    return f"[{citation_type.value}:{uuid[:8].lower()}]"


def format_mandate_citation(uuid: str) -> str:
    """Format a mandate citation."""
    return format_citation(uuid, CitationType.MANDATE)


def format_guardrail_citation(uuid: str) -> str:
    """Format a guardrail citation."""
    return format_citation(uuid, CitationType.GUARDRAIL)


def format_reference_citation(uuid: str) -> str:
    """Format a reference citation."""
    return format_citation(uuid, CitationType.REFERENCE)


def _parse_feedback_with_pattern(
    response_text: str, pattern: re.Pattern[str],
) -> list[FeedbackTag]:
    """Parse feedback tags using a specific regex pattern."""
    tags: list[FeedbackTag] = []
    for match in pattern.finditer(response_text):
        feedback_type = match.group(1).lower()
        component_id = match.group(2).lower()
        description = match.group(3).strip()
        if feedback_type not in VALID_FEEDBACK_TYPES:
            continue
        tags.append(FeedbackTag(
            feedback_type=feedback_type,
            component_id=component_id,
            description=description,
        ))
    return tags


def parse_feedback_tags(response_text: str) -> FeedbackParseResult:
    """Parse feedback tags from response text (new [[F:...]] then legacy [F:...] format)."""
    if not response_text:
        return FeedbackParseResult(tags=[])

    tags = _parse_feedback_with_pattern(response_text, FEEDBACK_TAG_PATTERN)
    if not tags:
        tags = _parse_feedback_with_pattern(response_text, FEEDBACK_TAG_PATTERN_LEGACY)

    counts = {t: sum(1 for tag in tags if tag.feedback_type == t) for t in VALID_FEEDBACK_TYPES}
    logger.debug("Parsed %d feedback tags from response", len(tags))
    return FeedbackParseResult(tags=tags, friction_count=counts["friction"],
        praise_count=counts["praise"], idea_count=counts["idea"],
        improvement_count=counts["improvement"])


def extract_feedback_tags(response_text: str) -> list[FeedbackTag]:
    """Convenience: extract feedback tags as list."""
    return parse_feedback_tags(response_text).tags


def parse_summary_tags(response_text: str) -> SummaryParseResult:
    """Parse [[S:outcome:description]] tags from response text."""
    if not response_text:
        return SummaryParseResult(tags=[])

    tags: list[SummaryTag] = []
    for match in SUMMARY_TAG_PATTERN.finditer(response_text):
        outcome = match.group(1).lower()
        if outcome not in VALID_SUMMARY_OUTCOMES:
            continue
        tags.append(SummaryTag(outcome=outcome, description=match.group(2).strip()))

    logger.debug("Parsed %d summary tags from response", len(tags))
    return SummaryParseResult(tags=tags)


def extract_summary_tags(response_text: str) -> list[SummaryTag]:
    """Convenience: extract summary tags as list."""
    return parse_summary_tags(response_text).tags
