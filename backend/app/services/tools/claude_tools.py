"""Claude tool calling support using Anthropic SDK."""

import logging
from dataclasses import dataclass, field
from typing import Any

from anthropic.types import ContentBlock, TextBlock, ToolUseBlock

from app.services.tools.base import (
    PreToolUseHook,
    ToolCall,
    ToolCaller,
    ToolDecision,
    ToolHandler,
    ToolRegistry,
    ToolResult,
)

logger = logging.getLogger(__name__)


@dataclass
class ServerToolUse:
    """Server-side tool use block (e.g., code_execution)."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class CodeExecutionResult:
    """Result from code execution tool."""

    stdout: str
    stderr: str
    return_code: int
    content: list[Any] = field(default_factory=list)  # Files created


@dataclass
class ContainerInfo:
    """Container information from API response."""

    id: str
    expires_at: str


@dataclass
class ClaudeToolResponse:
    """Response from Claude that may contain tool calls."""

    text_content: str
    tool_calls: list[ToolCall]
    stop_reason: str | None
    raw_blocks: list[ContentBlock]
    # Programmatic tool calling fields
    server_tool_uses: list[ServerToolUse] = field(default_factory=list)
    code_execution_results: list[CodeExecutionResult] = field(default_factory=list)
    container: ContainerInfo | None = None


def _extract_caller(block: Any) -> ToolCaller:
    """
    Extract caller information from a tool use block.

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

    return ToolCaller(type=caller_type, tool_id=tool_id)  # type: ignore[arg-type]


def parse_tool_calls(
    content_blocks: list[ContentBlock],
    container_data: dict[str, Any] | None = None,
) -> ClaudeToolResponse:
    """
    Parse Claude response content blocks to extract tool calls.

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
            # Handle server-side tool use (code_execution)
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
            # Handle code execution result
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


def format_tools_for_api(
    registry: ToolRegistry, include_code_execution: bool = False
) -> list[dict[str, Any]]:
    """
    Format tool registry for Claude API.

    Args:
        registry: ToolRegistry containing tool definitions
        include_code_execution: If True, include code_execution tool for
                               programmatic tool calling

    Returns:
        List of tool definitions in Claude format
    """
    return registry.to_api_format("claude", include_code_execution=include_code_execution)


def format_continuation_message(tool_results: list[ToolResult]) -> dict[str, Any]:
    """
    Format tool results as a continuation message for agentic loops.

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
