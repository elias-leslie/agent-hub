"""Claude tool handler with permission hooks."""

import logging
from typing import Any

from app.services.tools.base import (
    PreToolUseHook,
    ToolCall,
    ToolDecision,
    ToolHandler,
    ToolResult,
)

logger = logging.getLogger(__name__)


class ClaudeToolHandler(ToolHandler):
    """Tool handler for Claude with pre-execution hooks.

    Intercepts tool calls before execution, applying permission checks
    via the pre_hook callback.
    """

    def __init__(
        self,
        executor: dict[str, Any] | None = None,
        pre_hook: PreToolUseHook | None = None,
    ):
        """Initialize Claude tool handler.

        Args:
            executor: Optional dict mapping tool names to async callables
            pre_hook: Callback for permission checks before tool execution
        """
        super().__init__(pre_hook)
        self._executor = executor or {}

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call after permission check.

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
        """Process multiple tool calls in sequence.

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
