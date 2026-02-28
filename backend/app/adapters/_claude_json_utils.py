"""JSON extraction utilities for Claude adapter responses."""

import json
import logging
import re

logger = logging.getLogger(__name__)


def _try_parse_json(text: str) -> str | None:
    """Return text if it is valid JSON, else None."""
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        return None


def _extract_from_code_blocks(content: str) -> str | None:
    """Extract JSON from markdown fenced code blocks."""
    pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
    for match in re.findall(pattern, content):
        result = _try_parse_json(match.strip())
        if result is not None:
            logger.info("Extracted JSON from markdown code block")
            return result
    return None


def _extract_from_brace_pattern(content: str) -> str | None:
    """Extract first valid JSON object from content."""
    for match in re.findall(r"\{[\s\S]*\}", content):
        result = _try_parse_json(match)
        if result is not None:
            logger.info("Extracted JSON object from response")
            return result
    return None


def _extract_from_bracket_pattern(content: str) -> str | None:
    """Extract first valid JSON array from content."""
    for match in re.findall(r"\[[\s\S]*\]", content):
        result = _try_parse_json(match)
        if result is not None:
            logger.info("Extracted JSON array from response")
            return result
    return None


def extract_json_from_response(content: str) -> str:
    """Extract JSON from a response that may have surrounding text or markdown.

    Args:
        content: Raw response content that should contain JSON

    Returns:
        Extracted JSON string, or original content if extraction fails
    """
    content = content.strip()

    result = _try_parse_json(content)
    if result is not None:
        return result

    result = _extract_from_code_blocks(content)
    if result is not None:
        return result

    result = _extract_from_brace_pattern(content)
    if result is not None:
        return result

    result = _extract_from_bracket_pattern(content)
    if result is not None:
        return result

    logger.warning("Could not extract valid JSON from response")
    return str(content)
