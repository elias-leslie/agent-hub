"""Formatters for Claude tool API."""

from typing import Any

from app.services.tools.base import ToolRegistry, ToolResult


def format_tool_result(result: ToolResult) -> dict[str, Any]:
    """Format a tool result for Claude API.

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


def format_tools_for_api(
    registry: ToolRegistry, include_code_execution: bool = False
) -> list[dict[str, Any]]:
    """Format tool registry for Claude API.

    Args:
        registry: ToolRegistry containing tool definitions
        include_code_execution: If True, include code_execution tool for
                               programmatic tool calling

    Returns:
        List of tool definitions in Claude format
    """
    return registry.to_api_format("claude", include_code_execution=include_code_execution)


def format_continuation_message(tool_results: list[ToolResult]) -> dict[str, Any]:
    """Format tool results as a continuation message for agentic loops.

    When Claude returns tool_use blocks (especially from code execution),
    the results must be sent back in a user message containing only
    tool_result blocks.

    Args:
        tool_results: List of ToolResult objects to include

    Returns:
        User message dict with tool_result content blocks
    """
    return {
        "role": "user",
        "content": [format_tool_result(r) for r in tool_results],
    }
