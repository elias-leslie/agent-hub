"""Claude tool calling support using Anthropic SDK."""

import logging
from dataclasses import dataclass
from typing import Any

from anthropic.types import ContentBlock, TextBlock, ToolUseBlock

from app.services.tools.base import (
    PreToolUseHook,
    ToolCall,
    ToolDecision,
    ToolHandler,
    ToolRegistry,
    ToolResult,
)

logger = logging.getLogger(__name__)


@dataclass
class ClaudeToolResponse:
    """Response from Claude that may contain tool calls."""

    text_content: str
    tool_calls: list[ToolCall]
    stop_reason: str | None
    raw_blocks: list[ContentBlock]


def parse_tool_calls(content_blocks: list[ContentBlock]) -> ClaudeToolResponse:
    """
    Parse Claude response content blocks to extract tool calls.

    Args:
        content_blocks: Content blocks from Claude response

    Returns:
        ClaudeToolResponse with text and tool calls separated
    """
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in content_blocks:
        if isinstance(block, TextBlock):
            text_parts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            tool_calls.append(
                ToolCall(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                )
            )
            logger.debug(f"Parsed tool call: {block.name} (id={block.id})")

    return ClaudeToolResponse(
        text_content="".join(text_parts),
        tool_calls=tool_calls,
        stop_reason=None,
        raw_blocks=content_blocks,
    )


def format_tool_result(result: ToolResult) -> dict[str, Any]:
    """
    Format a tool result for Claude API.

    Args:
        result: ToolResult to format

    Returns:
        Dict in Claude tool_result format
    """
    return {
        "type": "tool_result",
        "tool_use_id": result.tool_use_id,
        "content": result.content,
        "is_error": result.is_error,
    }


def format_tools_for_api(registry: ToolRegistry) -> list[dict[str, Any]]:
    """
    Format tool registry for Claude API.

    Args:
        registry: ToolRegistry containing tool definitions

    Returns:
        List of tool definitions in Claude format
    """
    return registry.to_api_format("claude")


class ClaudeToolHandler(ToolHandler):
    """
    Tool handler for Claude with pre-execution hooks.

    Intercepts tool calls before execution, applying permission checks
    via the pre_hook callback.
    """

    def __init__(
        self,
        executor: dict[str, Any] | None = None,
        pre_hook: PreToolUseHook | None = None,
    ):
        """
        Initialize Claude tool handler.

        Args:
            executor: Optional dict mapping tool names to async callables
            pre_hook: Callback for permission checks before tool execution
        """
        super().__init__(pre_hook)
        self._executor = executor or {}

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """
        Execute a tool call after permission check.

        Args:
            tool_call: The tool call to execute

        Returns:
            ToolResult with output or error message
        """
        # Check permission first
        decision = await self.check_permission(tool_call)

        if decision == ToolDecision.DENY:
            logger.warning(f"Tool call denied: {tool_call.name}")
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Tool '{tool_call.name}' was denied by permission policy",
                is_error=True,
            )

        if decision == ToolDecision.ASK:
            logger.info(f"Tool call requires confirmation: {tool_call.name}")
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Tool '{tool_call.name}' requires user confirmation",
                is_error=True,
            )

        # Permission granted, execute
        executor_fn = self._executor.get(tool_call.name)
        if not executor_fn:
            logger.error(f"No executor for tool: {tool_call.name}")
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Tool '{tool_call.name}' not found",
                is_error=True,
            )

        try:
            logger.info(f"Executing tool: {tool_call.name}")
            result = await executor_fn(**tool_call.input)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=str(result),
                is_error=False,
            )
        except Exception as e:
            logger.exception(f"Tool execution failed: {tool_call.name}")
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error executing tool: {e}",
                is_error=True,
            )

    async def process_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """
        Process multiple tool calls in sequence.

        Args:
            tool_calls: List of tool calls to process

        Returns:
            List of ToolResult objects
        """
        results: list[ToolResult] = []
        for call in tool_calls:
            result = await self.execute(call)
            results.append(result)
        return results
