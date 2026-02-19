"""Utility functions for Claude adapter."""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _format_content(content: str | list[dict]) -> str:
    """Format message content, handling both string and multimodal content blocks.

    For string content, returns as-is. For multimodal content blocks (list of dicts),
    extracts text from text blocks and adds "[Image attached]" for image blocks.
    """
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "image":
                parts.append("[Image attached]")
        else:
            parts.append(str(block))
    return "\n".join(parts)


def build_claude_prompt(messages: list) -> str:
    """Build a flat prompt string from messages for the Claude SDK.

    Handles both string and multimodal content blocks.
    Formats as 'User: ...' / 'Assistant: ...' for multi-turn conversations.
    System messages are placed at the beginning of the prompt.

    For a single user message (no system or assistant), returns just the content
    without a role prefix.
    """
    system_parts: list[str] = []
    conversation_parts: list[str] = []
    for msg in messages:
        content = _format_content(msg.content)
        if msg.role == "system":
            system_parts.append(content)
        elif msg.role == "user":
            conversation_parts.append(f"User: {content}")
        elif msg.role == "assistant":
            conversation_parts.append(f"Assistant: {content}")

    all_parts = system_parts + conversation_parts

    # Single user message with no system context: return content without prefix
    if not system_parts and len(conversation_parts) == 1 and conversation_parts[0].startswith("User: "):
        return conversation_parts[0][len("User: "):]

    return "\n\n".join(all_parts) or "Hello"


def build_permission_checker(
    permission_config: dict[str, Any] | None,
) -> tuple[Any | None, bool]:
    """Parse permission_config and return (checker, yolo_mode).

    Returns:
        (None, True) when bypassing permissions (yolo mode).
        (PermissionChecker, False) when granular permission checking is needed.
    """
    from app.services.tools.permissions import (
        PermissionChecker,
        PermissionConfig,
        PermissionMode,
    )

    if not permission_config:
        return None, True
    config = PermissionConfig.from_dict(permission_config)
    if config.mode == PermissionMode.YOLO:
        return None, True
    return PermissionChecker(config), False

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
