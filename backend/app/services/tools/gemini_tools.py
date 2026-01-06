"""Gemini tool calling support using Google GenAI SDK."""

import logging
from dataclasses import dataclass
from typing import Any

from google.genai import types

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
class GeminiToolResponse:
    """Response from Gemini that may contain function calls."""

    text_content: str
    tool_calls: list[ToolCall]
    finish_reason: str | None
    raw_parts: list[types.Part]


def parse_function_calls(parts: list[types.Part]) -> GeminiToolResponse:
    """
    Parse Gemini response parts to extract function calls.

    Args:
        parts: Parts from Gemini response candidate

    Returns:
        GeminiToolResponse with text and function calls separated
    """
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for part in parts:
        if part.text:
            text_parts.append(part.text)
        elif part.function_call:
            fc = part.function_call
            # Convert args from Struct/dict to plain dict
            args = dict(fc.args) if fc.args else {}
            # Gemini may not always have id, use name as fallback
            call_id = fc.id or fc.name or "unknown"
            call_name = fc.name or "unknown"
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=call_name,
                    input=args,
                )
            )
            logger.debug(f"Parsed function call: {call_name} (id={fc.id})")

    return GeminiToolResponse(
        text_content="".join(text_parts),
        tool_calls=tool_calls,
        finish_reason=None,
        raw_parts=parts,
    )


def format_function_response(result: ToolResult) -> types.FunctionResponse:
    """
    Format a tool result for Gemini API.

    Args:
        result: ToolResult to format

    Returns:
        FunctionResponse in Gemini format
    """
    return types.FunctionResponse(
        id=result.tool_use_id,
        name=result.tool_use_id,  # Use id as name if no name available
        response={
            "result": result.content,
            "is_error": result.is_error,
        },
    )


def format_function_response_with_name(result: ToolResult, name: str) -> types.FunctionResponse:
    """
    Format a tool result for Gemini API with explicit name.

    Args:
        result: ToolResult to format
        name: The function name

    Returns:
        FunctionResponse in Gemini format
    """
    return types.FunctionResponse(
        id=result.tool_use_id,
        name=name,
        response={
            "result": result.content,
            "is_error": result.is_error,
        },
    )


def format_tools_for_api(registry: ToolRegistry) -> list[types.Tool]:
    """
    Format tool registry for Gemini API.

    Args:
        registry: ToolRegistry containing tool definitions

    Returns:
        List of Tool objects in Gemini format
    """
    function_declarations = []
    for tool in registry.tools:
        # Gemini expects parameters as Schema, but dict works via conversion
        func_decl = types.FunctionDeclaration(
            name=tool.name,
            description=tool.description,
            parameters=types.Schema(**tool.input_schema),
        )
        function_declarations.append(func_decl)

    if not function_declarations:
        return []

    return [types.Tool(function_declarations=function_declarations)]


class GeminiToolHandler(ToolHandler):
    """
    Tool handler for Gemini with pre-execution hooks.

    Intercepts function calls before execution, applying permission checks
    via the pre_hook callback.
    """

    def __init__(
        self,
        executor: dict[str, Any] | None = None,
        pre_hook: PreToolUseHook | None = None,
    ):
        """
        Initialize Gemini tool handler.

        Args:
            executor: Optional dict mapping function names to async callables
            pre_hook: Callback for permission checks before function execution
        """
        super().__init__(pre_hook)
        self._executor = executor or {}

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """
        Execute a function call after permission check.

        Args:
            tool_call: The function call to execute

        Returns:
            ToolResult with output or error message
        """
        # Check permission first
        decision = await self.check_permission(tool_call)

        if decision == ToolDecision.DENY:
            logger.warning(f"Function call denied: {tool_call.name}")
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Function '{tool_call.name}' was denied by permission policy",
                is_error=True,
            )

        if decision == ToolDecision.ASK:
            logger.info(f"Function call requires confirmation: {tool_call.name}")
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Function '{tool_call.name}' requires user confirmation",
                is_error=True,
            )

        # Permission granted, execute
        executor_fn = self._executor.get(tool_call.name)
        if not executor_fn:
            logger.error(f"No executor for function: {tool_call.name}")
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Function '{tool_call.name}' not found",
                is_error=True,
            )

        try:
            logger.info(f"Executing function: {tool_call.name}")
            result = await executor_fn(**tool_call.input)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=str(result),
                is_error=False,
            )
        except Exception as e:
            logger.exception(f"Function execution failed: {tool_call.name}")
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error executing function: {e}",
                is_error=True,
            )

    async def process_function_calls(
        self, function_calls: list[ToolCall]
    ) -> list[tuple[ToolResult, str]]:
        """
        Process multiple function calls in sequence.

        Args:
            function_calls: List of function calls to process

        Returns:
            List of (ToolResult, function_name) tuples
        """
        results: list[tuple[ToolResult, str]] = []
        for call in function_calls:
            result = await self.execute(call)
            results.append((result, call.name))
        return results
