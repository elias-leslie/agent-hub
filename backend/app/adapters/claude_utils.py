"""Utility functions for Claude adapter."""

import asyncio
import logging
import os

from app.adapters._claude_constants import DEFAULT_ALLOWED_CLI_TOOLS as DEFAULT_ALLOWED_CLI_TOOLS
from app.adapters._claude_constants import READ_TOOLS as READ_TOOLS
from app.adapters._claude_constants import THINKING_LEVEL_TO_EFFORT
from app.adapters._claude_constants import WRITE_TOOLS as WRITE_TOOLS
from app.adapters._claude_json_utils import extract_json_from_response as extract_json_from_response
from app.adapters._claude_sdk_builder import build_sdk_options as build_sdk_options

logger = logging.getLogger(__name__)

# Limits concurrent Claude CLI subprocesses (~200-400MB RSS each) to prevent OOM.
# Note: The semaphore is created at import time, so env var changes require a restart.
_MAX_CONCURRENT_SDK_SESSIONS_DEFAULT = 6
_raw_max_sessions = os.environ.get("MAX_CONCURRENT_SDK_SESSIONS", str(_MAX_CONCURRENT_SDK_SESSIONS_DEFAULT))
try:
    _parsed_max_sessions = int(_raw_max_sessions)
    if _parsed_max_sessions <= 0:
        logger.warning(
            f"MAX_CONCURRENT_SDK_SESSIONS env var has non-positive value '{_raw_max_sessions}', "
            f"falling back to default {_MAX_CONCURRENT_SDK_SESSIONS_DEFAULT}"
        )
        MAX_CONCURRENT_SDK_SESSIONS = _MAX_CONCURRENT_SDK_SESSIONS_DEFAULT
    else:
        MAX_CONCURRENT_SDK_SESSIONS = _parsed_max_sessions
except ValueError:
    logger.warning(
        f"MAX_CONCURRENT_SDK_SESSIONS env var has invalid value '{_raw_max_sessions}', "
        f"falling back to default {_MAX_CONCURRENT_SDK_SESSIONS_DEFAULT}"
    )
    MAX_CONCURRENT_SDK_SESSIONS = _MAX_CONCURRENT_SDK_SESSIONS_DEFAULT
_sdk_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SDK_SESSIONS)


def _block_text(block: object) -> str:
    """Return plain-text for a single multimodal content block."""
    if not isinstance(block, dict):
        return str(block)
    block_type = block.get("type")
    if block_type == "text":
        text = block.get("text")
        return str(text) if text is not None else ""
    if block_type == "image":
        return "[Image attached]"
    return ""


def _format_content(content: str | list[dict[str, object]]) -> str:
    """Format message content, handling both string and multimodal content blocks."""
    if isinstance(content, str):
        return content
    return "\n".join(_block_text(block) for block in content)


_ROLE_PREFIX: dict[str, str] = {"user": "User", "assistant": "Assistant"}


def _classify_message(
    msg: object,
    system_parts: list[str],
    conversation_parts: list[str],
) -> None:
    """Append msg content to the appropriate bucket based on its role."""
    role = getattr(msg, "role", "")
    content = _format_content(getattr(msg, "content", ""))
    if role == "system":
        system_parts.append(content)
        return
    prefix = _ROLE_PREFIX.get(role)
    if prefix is not None:
        conversation_parts.append(f"{prefix}: {content}")


def _partition_messages(messages: list[object]) -> tuple[list[str], list[str]]:
    """Split messages into system and conversation parts."""
    system_parts: list[str] = []
    conversation_parts: list[str] = []
    for msg in messages:
        _classify_message(msg, system_parts, conversation_parts)
    return system_parts, conversation_parts


def _unwrap_single_user(system_parts: list[str], conversation_parts: list[str]) -> str:
    """Return bare content when there is one user turn and no system context."""
    if not system_parts and len(conversation_parts) == 1 and conversation_parts[0].startswith("User: "):
        return conversation_parts[0][len("User: "):]
    return "\n\n".join(system_parts + conversation_parts) or "Hello"


def build_claude_prompt(messages: list[object]) -> str:
    """Build a flat Claude SDK prompt; multi-turn prefixes roles, single user returns bare."""
    system_parts, conversation_parts = _partition_messages(messages)
    return _unwrap_single_user(system_parts, conversation_parts)


def extract_system_and_conversation(messages: list[object]) -> tuple[str | None, str]:
    """Return (system_prompt, conversation_prompt) separated for SDK system_prompt arg."""
    system_parts, conversation_parts = _partition_messages(messages)
    system_prompt = "\n\n".join(system_parts) if system_parts else None
    conversation = _unwrap_single_user([], conversation_parts)
    return system_prompt, conversation


def get_claude_thinking_config(thinking_level: str | None) -> dict[str, object] | None:
    """Convert thinking_level to Claude SDK ThinkingConfig dict, or None."""
    if not thinking_level:
        return None
    effort = THINKING_LEVEL_TO_EFFORT.get(thinking_level)
    if effort is None:
        return {"type": "disabled"}
    return {"type": "adaptive", "effort": effort}


def is_thinking_block(block: object) -> bool:
    """Check if an SDK block is a ThinkingBlock."""
    return type(block).__name__ == "ThinkingBlock" or (
        hasattr(block, "type") and getattr(block, "type", None) == "thinking"
    )


def is_tool_use_block(block: object) -> bool:
    """Check if an SDK block is a ToolUseBlock."""
    return type(block).__name__ == "ToolUseBlock" or (
        hasattr(block, "type") and getattr(block, "type", None) == "tool_use"
    )


def _extract_tool_use(block: object) -> dict[str, object]:
    """Build the content dict for a ToolUseBlock."""
    result: dict[str, object] = {
        "type": "tool_use",
        "id": getattr(block, "id", ""),
        "name": getattr(block, "name", "unknown"),
        "input": getattr(block, "input", {}),
    }
    if result["name"] == "StructuredOutput" and result["input"]:
        result["structured_output"] = result["input"]
    return result


def extract_block_content(block: object) -> dict[str, object]:
    """Extract content from an SDK message block; returns dict with type and block-specific keys."""
    block_type_name = type(block).__name__
    attr_type = getattr(block, "type", None)
    if block_type_name == "TextBlock" or attr_type == "text":
        return {"type": "text", "text": getattr(block, "text", "")}
    if is_thinking_block(block):
        thinking = getattr(block, "thinking", "") or getattr(block, "text", "")
        return {"type": "thinking", "thinking": thinking}
    if is_tool_use_block(block):
        return _extract_tool_use(block)
    if block_type_name == "ToolResultBlock" or attr_type == "tool_result":
        content = getattr(block, "content", "")
        return {
            "type": "tool_result",
            "tool_use_id": getattr(block, "tool_use_id", ""),
            "content": content if isinstance(content, str) else str(content or ""),
            "is_error": getattr(block, "is_error", False),
        }
    return {"type": "unknown"}
