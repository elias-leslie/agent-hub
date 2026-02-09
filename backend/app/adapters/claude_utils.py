"""Utility functions for Claude adapter."""

import json
import logging
import re

logger = logging.getLogger(__name__)

# Thinking level to budget tokens mapping for Claude
THINKING_LEVEL_BUDGETS = {
    "minimal": None,  # Disabled
    "low": 1024,
    "medium": 4096,
    "high": 16384,
    "ultrathink": 65536,
}

# Tool categories for permission handling
READ_TOOLS = {"read_file", "search_code", "list_files", "get_project_structure"}
WRITE_TOOLS = {"write_file", "edit_file", "delete_file", "create_directory"}


def get_claude_thinking_budget(thinking_level: str | None) -> int | None:
    """Convert thinking_level to Claude's token budget.

    Args:
        thinking_level: Semantic level (minimal/low/medium/high/ultrathink)

    Returns:
        Token budget for Claude's max_thinking_tokens, or None to disable
    """
    if thinking_level:
        return THINKING_LEVEL_BUDGETS.get(thinking_level)
    return None


def extract_json_from_response(content: str) -> str:
    """Extract JSON from a response that may have surrounding text or markdown.

    Args:
        content: Raw response content that should contain JSON

    Returns:
        Extracted JSON string, or original content if extraction fails
    """
    content = content.strip()

    # Try parsing as-is first
    try:
        json.loads(content)
        return str(content)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code blocks
    # Match ```json ... ``` or ``` ... ```
    code_block_pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
    matches = re.findall(code_block_pattern, content)
    for match in matches:
        try:
            json.loads(match.strip())
            logger.info("Extracted JSON from markdown code block")
            return str(match.strip())
        except json.JSONDecodeError:
            continue

    # Try finding JSON object pattern { ... }
    brace_pattern = r"\{[\s\S]*\}"
    matches = re.findall(brace_pattern, content)
    for match in matches:
        try:
            json.loads(match)
            logger.info("Extracted JSON object from response")
            return str(match)
        except json.JSONDecodeError:
            continue

    # Try finding JSON array pattern [ ... ]
    bracket_pattern = r"\[[\s\S]*\]"
    matches = re.findall(bracket_pattern, content)
    for match in matches:
        try:
            json.loads(match)
            logger.info("Extracted JSON array from response")
            return str(match)
        except json.JSONDecodeError:
            continue

    # Return original if no valid JSON found
    logger.warning("Could not extract valid JSON from response")
    return str(content)
