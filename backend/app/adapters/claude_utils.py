"""Utility functions for Claude adapter."""

import asyncio
import logging
from typing import Any

from app.adapters._claude_constants import (
    DEFAULT_ALLOWED_CLI_TOOLS as DEFAULT_ALLOWED_CLI_TOOLS,
)
from app.adapters._claude_constants import (
    READ_TOOLS as READ_TOOLS,
)
from app.adapters._claude_constants import (
    THINKING_LEVEL_TO_EFFORT,
)
from app.adapters._claude_constants import (
    WRITE_TOOLS as WRITE_TOOLS,
)
from app.adapters._claude_json_utils import extract_json_from_response as extract_json_from_response
from app.adapters._claude_sdk_builder import build_sdk_options as build_sdk_options

logger = logging.getLogger(__name__)

# Global semaphore limiting concurrent Claude SDK subprocess sessions.
# Each SDK session spawns a Claude CLI subprocess (~200-400MB RSS).
# Default of 3 prevents OOM on a typical 8GB server.
MAX_CONCURRENT_SDK_SESSIONS = 3
_sdk_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SDK_SESSIONS)

# Re-export constants under legacy names for backward compatibility
_THINKING_LEVEL_TO_EFFORT = THINKING_LEVEL_TO_EFFORT


def _format_content(content: str | list[dict]) -> str:
    """Format message content, handling both string and multimodal content blocks."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(str(block))
        elif block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "image":
            parts.append("[Image attached]")
    return "\n".join(parts)


def _partition_messages(messages: list) -> tuple[list[str], list[str]]:
    """Split messages into system and conversation parts."""
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
    return system_parts, conversation_parts


def _unwrap_single_user(system_parts: list[str], conversation_parts: list[str]) -> str:
    """Return bare content when there is one user turn and no system context."""
    if not system_parts and len(conversation_parts) == 1 and conversation_parts[0].startswith("User: "):
        return conversation_parts[0][len("User: "):]
    return "\n\n".join(system_parts + conversation_parts) or "Hello"


def build_claude_prompt(messages: list) -> str:
    """Build a flat prompt string from messages for the Claude SDK.

    Handles both string and multimodal content blocks.
    Formats as 'User: ...' / 'Assistant: ...' for multi-turn conversations.
    System messages are placed at the beginning of the prompt.

    For a single user message (no system or assistant), returns just the content
    without a role prefix.
    """
    system_parts, conversation_parts = _partition_messages(messages)
    return _unwrap_single_user(system_parts, conversation_parts)


def extract_system_and_conversation(messages: list) -> tuple[str | None, str]:
    """Separate system content from conversation for SDK system_prompt.

    Returns (system_prompt, conversation_prompt).
    """
    system_parts, conversation_parts = _partition_messages(messages)
    system_prompt = "\n\n".join(system_parts) if system_parts else None

    if not system_parts and len(conversation_parts) == 1 and conversation_parts[0].startswith("User: "):
        conversation = conversation_parts[0][len("User: "):]
    else:
        conversation = "\n\n".join(conversation_parts) or "Hello"

    return system_prompt, conversation


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


def get_claude_thinking_config(thinking_level: str | None) -> Any:
    """Convert thinking_level to Claude SDK ThinkingConfig.

    Args:
        thinking_level: Semantic level (minimal/low/medium/high/ultrathink)

    Returns:
        ThinkingConfig dict for ClaudeAgentOptions, or None for default behavior
    """
    if not thinking_level:
        return None
    effort = THINKING_LEVEL_TO_EFFORT.get(thinking_level)
    if effort is None:
        return {"type": "disabled"}
    return {"type": "adaptive", "effort": effort}


def is_thinking_block(block: Any) -> bool:
    """Check if an SDK block is a ThinkingBlock."""
    return type(block).__name__ == "ThinkingBlock" or (
        hasattr(block, "type") and getattr(block, "type", None) == "thinking"
    )


def is_tool_use_block(block: Any) -> bool:
    """Check if an SDK block is a ToolUseBlock."""
    return type(block).__name__ == "ToolUseBlock" or (
        hasattr(block, "type") and getattr(block, "type", None) == "tool_use"
    )


def extract_block_content(block: Any) -> dict[str, Any]:
    """Extract content from an SDK message block.

    Returns dict with type and block-specific keys.
    """
    block_type_name = type(block).__name__

    if block_type_name == "TextBlock" or getattr(block, "type", None) == "text":
        return {"type": "text", "text": getattr(block, "text", "")}

    if is_thinking_block(block):
        thinking = getattr(block, "thinking", "") or getattr(block, "text", "")
        return {"type": "thinking", "thinking": thinking}

    if is_tool_use_block(block):
        result: dict[str, Any] = {
            "type": "tool_use",
            "id": getattr(block, "id", ""),
            "name": getattr(block, "name", "unknown"),
            "input": getattr(block, "input", {}),
        }
        if result["name"] == "StructuredOutput" and result["input"]:
            result["structured_output"] = result["input"]
        return result

    if block_type_name == "ToolResultBlock" or getattr(block, "type", None) == "tool_result":
        content = getattr(block, "content", "")
        return {
            "type": "tool_result",
            "tool_use_id": getattr(block, "tool_use_id", ""),
            "content": content if isinstance(content, str) else str(content or ""),
            "is_error": getattr(block, "is_error", False),
        }

    return {"type": "unknown"}
