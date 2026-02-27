"""Utility functions for Claude adapter."""

import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Global semaphore limiting concurrent Claude SDK subprocess sessions.
# Each SDK session spawns a Claude CLI subprocess (~200-400MB RSS).
# Default of 3 prevents OOM on a typical 8GB server.
MAX_CONCURRENT_SDK_SESSIONS = 3
_sdk_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SDK_SESSIONS)


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


def extract_system_and_conversation(messages: list) -> tuple[str | None, str]:
    """Separate system content from conversation for SDK system_prompt.

    Returns (system_prompt, conversation_prompt).
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


# Thinking level → SDK effort mapping for Claude
_THINKING_LEVEL_TO_EFFORT: dict[str, str | None] = {
    "minimal": None,       # Disabled
    "low": "low",
    "medium": "medium",
    "high": "high",
    "ultrathink": "max",
}

# CLI-builtin tools to expose by default (MCP tools are separate)
DEFAULT_ALLOWED_CLI_TOOLS = ["Read", "Write", "Bash", "Edit", "Glob", "Grep"]


def get_claude_thinking_config(thinking_level: str | None) -> Any:
    """Convert thinking_level to Claude SDK ThinkingConfig.

    Args:
        thinking_level: Semantic level (minimal/low/medium/high/ultrathink)

    Returns:
        ThinkingConfig dict for ClaudeAgentOptions, or None for default behavior
    """
    if not thinking_level:
        return None
    effort = _THINKING_LEVEL_TO_EFFORT.get(thinking_level)
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

    Returns dict with:
      - "type": "text" | "thinking" | "tool_use" | "tool_result" | "unknown"
      - For text: "text" key with the text content
      - For thinking: "thinking" key with thinking content
      - For tool_use: "id", "name", "input" keys
        If name == "StructuredOutput", also "structured_output" key
      - For tool_result: "tool_use_id", "content", "is_error" keys
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


def build_sdk_options(
    cli_path: str,
    model: str,
    model_map: dict[str, str],
    working_dir: str | None = None,
    yolo_mode: bool = True,
    can_use_tool: Any | None = None,
    mcp_servers: dict[str, Any] | None = None,
    resume_session_id: str | None = None,
    json_mode: bool = False,
    json_schema: dict[str, Any] | None = None,
    thinking_level: str | None = None,
    max_turns: int | None = None,
    allowed_tools: list[str] | None = None,
    system_prompt: str | None = None,
) -> tuple[Any, bool]:
    """Build ClaudeAgentOptions. Returns (options, use_streaming_prompt).

    Unified builder for all Claude adapter paths (oauth, streaming, tools).
    Pre-built ``can_use_tool`` callbacks and ``mcp_servers`` dicts are passed
    in by callers that need tool-specific SDK features.
    """
    from claude_agent_sdk import ClaudeAgentOptions

    from app.services.tools.project_env import build_venv_env_overlay

    sdk_model = model_map.get(model, model)
    cwd = working_dir or "."

    sdk_opts: dict[str, Any] = {
        "cwd": cwd,
        "cli_path": cli_path,
        "model": sdk_model,
        "env": build_venv_env_overlay(cwd),
        "enable_file_checkpointing": True,
        "max_buffer_size": 10 * 1024 * 1024,  # 10 MB
        "max_budget_usd": 5.0,
    }

    use_streaming_prompt = False
    if yolo_mode and can_use_tool is None:
        sdk_opts["permission_mode"] = "bypassPermissions"
    elif can_use_tool is not None:
        sdk_opts["can_use_tool"] = can_use_tool
        use_streaming_prompt = True

    thinking = get_claude_thinking_config(thinking_level)
    if thinking is not None:
        sdk_opts["thinking"] = thinking

    if max_turns is not None:
        sdk_opts["max_turns"] = max_turns

    if json_mode and json_schema:
        sdk_opts["output_format"] = {"type": "json_schema", "schema": json_schema}
        sdk_opts["max_turns"] = 2  # json_mode always overrides

    if resume_session_id:
        sdk_opts["resume"] = resume_session_id
        logger.info("SDK options: resuming session %s", resume_session_id)

    if mcp_servers:
        sdk_opts["mcp_servers"] = mcp_servers
        use_streaming_prompt = True

    sdk_opts["allowed_tools"] = allowed_tools or DEFAULT_ALLOWED_CLI_TOOLS

    if system_prompt:
        sdk_opts["system_prompt"] = system_prompt

    return ClaudeAgentOptions(**sdk_opts), use_streaming_prompt


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
