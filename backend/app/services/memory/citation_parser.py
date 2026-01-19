"""
Citation parser for extracting rule IDs from LLM responses.

Parses citations in the format [M:uuid8] (mandates) and [G:uuid8] (guardrails)
from LLM responses to track which rules were actually referenced/used.

Citation format per decision d3:
- [M:abc12345] - Mandate citation (8-char hex UUID prefix)
- [G:def67890] - Guardrail citation (8-char hex UUID prefix)

This allows tracking which rules are being actively used vs just loaded,
enabling utility_score calculation for prioritization.
"""

import logging
import re
from enum import Enum

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Regex pattern for citations: [M:8-char-hex] or [G:8-char-hex]
# The 8-char hex is the first 8 characters of the full UUID
CITATION_PATTERN = re.compile(r"\[([MG]):([a-f0-9]{8})\]", re.IGNORECASE)


class CitationType(str, Enum):
    """Type of citation."""

    MANDATE = "M"
    GUARDRAIL = "G"


class Citation(BaseModel):
    """A parsed citation from LLM response."""

    type: CitationType
    uuid_prefix: str  # 8-char hex prefix of the full UUID


class ParseResult(BaseModel):
    """Result of parsing citations from a response."""

    citations: list[Citation]
    mandate_count: int = 0
    guardrail_count: int = 0
    unique_uuids: list[str] = []


def parse_citations(response_text: str) -> ParseResult:
    """
    Parse citations from an LLM response.

    Extracts all [M:uuid8] and [G:uuid8] citations from the response text.

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
        else:
            guardrail_count += 1

    logger.debug(
        "Parsed %d citations (%d mandates, %d guardrails) from response",
        len(citations),
        mandate_count,
        guardrail_count,
    )

    return ParseResult(
        citations=citations,
        mandate_count=mandate_count,
        guardrail_count=guardrail_count,
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
    Resolve 8-char UUID prefixes to full UUIDs from Neo4j.

    Queries Neo4j to find Episodic nodes whose UUIDs start with
    the given prefixes.

    Args:
        uuid_prefixes: List of 8-char UUID prefixes
        group_id: Graphiti group ID for scoping

    Returns:
        Dict mapping prefix -> full UUID
    """
    if not uuid_prefixes:
        return {}

    from .graphiti_client import get_graphiti

    graphiti = get_graphiti()
    driver = graphiti.driver

    # Query for all matching prefixes
    query = """
    UNWIND $prefixes AS prefix
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.uuid STARTS WITH prefix
    RETURN prefix, e.uuid AS full_uuid
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            prefixes=uuid_prefixes,
            group_id=group_id,
        )

        result = {r["prefix"]: r["full_uuid"] for r in records}
        logger.debug("Resolved %d/%d UUID prefixes", len(result), len(uuid_prefixes))
        return result

    except Exception as e:
        logger.error("Failed to resolve UUID prefixes: %s", e)
        return {}


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
