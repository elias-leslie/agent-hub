"""Parsing Claude response content blocks for tool calls."""

import logging
from typing import Any

from anthropic.types import ContentBlock, TextBlock, ToolUseBlock

from app.services.tools.base import ToolCall, ToolCaller
from app.services.tools.claude_types import (
    ClaudeToolResponse,
    CodeExecutionResult,
    ContainerInfo,
    ServerToolUse,
)

logger = logging.getLogger(__name__)


def _extract_caller(block: Any) -> ToolCaller:
    """Extract caller information from a tool use block.

    Args:
        block: ToolUseBlock or dict with potential caller field

    Returns:
        ToolCaller with appropriate type and tool_id
    """
    # Handle both typed SDK objects and raw dicts
    caller_data = getattr(block, "caller", None)
    if caller_data is None and isinstance(block, dict):
        caller_data = block.get("caller")

    if caller_data is None:
        return ToolCaller(type="direct")

    # Extract caller type and tool_id
    if isinstance(caller_data, dict):
        caller_type = caller_data.get("type", "direct")
        tool_id = caller_data.get("tool_id")
    else:
        caller_type = getattr(caller_data, "type", "direct")
        tool_id = getattr(caller_data, "tool_id", None)

    # Validate caller type
    if caller_type not in ("direct", "code_execution_20250825"):
        logger.warning(f"Unknown caller type: {caller_type}, defaulting to direct")
        caller_type = "direct"

    return ToolCaller(type=caller_type, tool_id=tool_id)


def parse_tool_calls(
    content_blocks: list[ContentBlock],
    container_data: dict[str, Any] | None = None,
) -> ClaudeToolResponse:
    """Parse Claude response content blocks to extract tool calls.

    Handles both direct tool calls and programmatic tool calls from
    code execution.

    Args:
        content_blocks: Content blocks from Claude response
        container_data: Optional container info from API response

    Returns:
        ClaudeToolResponse with text, tool calls, and server tool uses
    """
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    server_tool_uses: list[ServerToolUse] = []
    code_execution_results: list[CodeExecutionResult] = []

    for block in content_blocks:
        block_type = getattr(block, "type", None)

        if isinstance(block, TextBlock):
            text_parts.append(block.text)

        elif isinstance(block, ToolUseBlock):
            caller = _extract_caller(block)
            tool_calls.append(
                ToolCall(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                    caller=caller,
                )
            )
            if caller.type == "code_execution_20250825":
                logger.debug(
                    f"Parsed programmatic tool call: {block.name} "
                    f"(id={block.id}, from={caller.tool_id})"
                )
            else:
                logger.debug(f"Parsed direct tool call: {block.name} (id={block.id})")

        elif block_type == "server_tool_use":
            server_tool_uses.append(
                ServerToolUse(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    input=getattr(block, "input", {}),
                )
            )
            logger.debug(
                f"Parsed server tool use: {getattr(block, 'name', '')} "
                f"(id={getattr(block, 'id', '')})"
            )

        elif block_type == "code_execution_tool_result":
            content = getattr(block, "content", None)
            content_type = getattr(content, "type", None) if content else None
            if content_type == "code_execution_result":
                code_execution_results.append(
                    CodeExecutionResult(
                        stdout=getattr(content, "stdout", ""),
                        stderr=getattr(content, "stderr", ""),
                        return_code=getattr(content, "return_code", 0),
                        content=getattr(content, "content", []),
                    )
                )

    # Parse container info if provided
    container = None
    if container_data:
        container = ContainerInfo(
            id=container_data.get("id", ""),
            expires_at=container_data.get("expires_at", ""),
        )

    return ClaudeToolResponse(
        text_content="".join(text_parts),
        tool_calls=tool_calls,
        stop_reason=None,
        raw_blocks=content_blocks,
        server_tool_uses=server_tool_uses,
        code_execution_results=code_execution_results,
        container=container,
    )
