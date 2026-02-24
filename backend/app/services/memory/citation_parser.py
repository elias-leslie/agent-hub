"""
Citation parser for extracting rule IDs from LLM responses.

Parses citations in the format [M:uuid8] (mandates) and [G:uuid8] (guardrails)
from LLM responses to track which rules were actually referenced/used.

Citation format per decision d3:
- [M:abc12345] - Mandate citation (8-char hex UUID prefix)
- [G:def67890] - Guardrail citation (8-char hex UUID prefix)
- [R:11223344] - Reference citation (8-char hex UUID prefix)

This allows tracking which rules are being actively used vs just loaded,
enabling utility_score calculation for prioritization.
"""

import logging
import re
from enum import StrEnum

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Regex pattern for citations: [M:8-char-hex], [G:8-char-hex], or [R:8-char-hex]
# The 8-char hex is the first 8 characters of the full UUID
CITATION_PATTERN = re.compile(r"\[([MGR]):([a-f0-9]{8})\]", re.IGNORECASE)


class CitationType(StrEnum):
    """Type of citation."""

    MANDATE = "M"
    GUARDRAIL = "G"
    REFERENCE = "R"


class Citation(BaseModel):
    """A parsed citation from LLM response."""

    type: CitationType
    uuid_prefix: str  # 8-char hex prefix of the full UUID


class ParseResult(BaseModel):
    """Result of parsing citations from a response."""

    citations: list[Citation]
    mandate_count: int = 0
    guardrail_count: int = 0
    reference_count: int = 0
    unique_uuids: list[str] = []


def parse_citations(response_text: str) -> ParseResult:
    """
    Parse citations from an LLM response.

    Extracts all [M:uuid8], [G:uuid8], and [R:uuid8] citations from the response text.

    Args:
        response_text: The LLM response text to parse

    Returns:
        ParseResult with list of citations and counts

    Example:
        >>> result = parse_citations("Per [M:abc12345], we should...")
        >>> result.citations[0].type
        CitationType.MANDATE
        >>> result.citations[0].uuid_prefix
        'abc12345'
    """
    if not response_text:
        return ParseResult(citations=[], unique_uuids=[])

    citations: list[Citation] = []
    seen_uuids: set[str] = set()
    mandate_count = 0
    guardrail_count = 0
    reference_count = 0

    for match in CITATION_PATTERN.finditer(response_text):
        citation_type = match.group(1).upper()
        uuid_prefix = match.group(2).lower()

        try:
            ctype = CitationType(citation_type)
        except ValueError:
            logger.warning("Unknown citation type: %s", citation_type)
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
        len(citations),
        mandate_count,
        guardrail_count,
        reference_count,
    )

    return ParseResult(
        citations=citations,
        mandate_count=mandate_count,
        guardrail_count=guardrail_count,
        reference_count=reference_count,
        unique_uuids=list(seen_uuids),
    )


def extract_uuid_prefixes(response_text: str) -> list[str]:
    """
    Extract just the UUID prefixes from citations.

    Convenience function that returns only the unique UUID prefixes
    without citation type information.

    Args:
        response_text: The LLM response text to parse

    Returns:
        List of unique 8-char UUID prefixes found
    """
    result = parse_citations(response_text)
    return result.unique_uuids


async def resolve_full_uuids(
    uuid_prefixes: list[str],
    group_id: str = "global",
) -> dict[str, str]:
    """
    Resolve 8-char UUID prefixes to full UUIDs from PostgreSQL.

    Queries the memories table to find records whose UUIDs start with
    the given prefixes.

    Args:
        uuid_prefixes: List of 8-char UUID prefixes
        group_id: Group ID for scoping (searches both project and global)

    Returns:
        Dict mapping prefix -> full UUID
    """
    if not uuid_prefixes:
        return {}

    from .repository import get_memory_repository

    repo = get_memory_repository()
    result: dict[str, str] = {}

    for prefix in uuid_prefixes:
        try:
            full_uuid = await repo.resolve_uuid_prefix(prefix, group_id=group_id)
            result[prefix] = full_uuid
        except ValueError:
            # Try global scope if not found in project scope
            if group_id != "global":
                try:
                    full_uuid = await repo.resolve_uuid_prefix(prefix, group_id="global")
                    result[prefix] = full_uuid
                except ValueError:
                    logger.debug("Could not resolve UUID prefix: %s", prefix)
            else:
                logger.debug("Could not resolve UUID prefix: %s", prefix)

    logger.debug("Resolved %d/%d UUID prefixes", len(result), len(uuid_prefixes))
    return result


def format_citation(uuid: str, citation_type: CitationType) -> str:
    """
    Format a UUID into a citation string.

    Args:
        uuid: The full UUID
        citation_type: MANDATE or GUARDRAIL

    Returns:
        Citation string like [M:abc12345]
    """
    prefix = uuid[:8].lower()
    return f"[{citation_type.value}:{prefix}]"


def format_mandate_citation(uuid: str) -> str:
    """Format a mandate citation."""
    return format_citation(uuid, CitationType.MANDATE)


def format_guardrail_citation(uuid: str) -> str:
    """Format a guardrail citation."""
    return format_citation(uuid, CitationType.GUARDRAIL)


def format_reference_citation(uuid: str) -> str:
    """Format a reference citation."""
    return format_citation(uuid, CitationType.REFERENCE)


# --- Inline feedback tag parsing ---
# Format: [F:friction:sf.cli] error message unhelpful when flag is invalid
FEEDBACK_TAG_PATTERN = re.compile(
    r"\[F:(friction|idea|improvement|praise):([a-z][a-z0-9]*\.[a-z_]+)\]\s*(.*?)(?:\n|$)",
    re.IGNORECASE,
)

VALID_FEEDBACK_TYPES = {"friction", "idea", "improvement", "praise"}


class FeedbackTag(BaseModel):
    """A parsed inline feedback tag from LLM response."""

    feedback_type: str  # friction, idea, improvement, praise
    component_id: str  # sf.cli, ah.memory, etc.
    description: str  # trailing text after the tag


class FeedbackParseResult(BaseModel):
    """Result of parsing feedback tags from a response."""

    tags: list[FeedbackTag]
    friction_count: int = 0
    praise_count: int = 0
    idea_count: int = 0
    improvement_count: int = 0


def parse_feedback_tags(response_text: str) -> FeedbackParseResult:
    """Parse [F:type:component] tags from response text.

    Args:
        response_text: The LLM response text to parse

    Returns:
        FeedbackParseResult with list of tags and counts

    Example:
        >>> result = parse_feedback_tags("[F:friction:sf.cli] bad error message")
        >>> result.tags[0].feedback_type
        'friction'
    """
    if not response_text:
        return FeedbackParseResult(tags=[])

    tags: list[FeedbackTag] = []
    counts: dict[str, int] = {
        "friction": 0,
        "praise": 0,
        "idea": 0,
        "improvement": 0,
    }

    for match in FEEDBACK_TAG_PATTERN.finditer(response_text):
        feedback_type = match.group(1).lower()
        component_id = match.group(2).lower()
        description = match.group(3).strip()

        if feedback_type not in VALID_FEEDBACK_TYPES:
            continue

        tags.append(
            FeedbackTag(
                feedback_type=feedback_type,
                component_id=component_id,
                description=description,
            )
        )
        counts[feedback_type] += 1

    logger.debug("Parsed %d feedback tags from response", len(tags))

    return FeedbackParseResult(
        tags=tags,
        friction_count=counts["friction"],
        praise_count=counts["praise"],
        idea_count=counts["idea"],
        improvement_count=counts["improvement"],
    )


def extract_feedback_tags(response_text: str) -> list[FeedbackTag]:
    """Convenience: extract feedback tags as list."""
    return parse_feedback_tags(response_text).tags
