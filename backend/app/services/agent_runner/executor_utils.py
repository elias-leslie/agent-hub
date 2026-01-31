"""Shared utilities for executor implementations."""

import logging
from typing import Any

from app.adapters.base import Message
from app.services.memory import track_referenced_batch
from app.services.memory.citation_parser import extract_uuid_prefixes, resolve_full_uuids
from app.services.tools.base import ToolCall, ToolResult

from .models import AgentProgress, AgentResult

logger = logging.getLogger(__name__)


async def emit_progress(
    result: AgentResult,
    turn: int,
    status: str,
    message: str,
    callback: Any | None = None,
    **kwargs: Any,
) -> None:
    """Create progress entry and invoke callback if provided."""
    progress = AgentProgress(turn=turn, status=status, message=message, **kwargs)
    result.progress_log.append(progress)
    if callback:
        await callback(progress)


def track_tokens(result: AgentResult, input_tokens: int, output_tokens: int) -> None:
    """Add tokens to result totals."""
    result.input_tokens += input_tokens
    result.output_tokens += output_tokens


async def extract_and_track_citations(content: str, group_id: str, turn: int) -> set[str]:
    """Extract UUID citations from content and track them."""
    cited_uuids: set[str] = set()
    prefixes = extract_uuid_prefixes(content)
    if prefixes:
        prefix_map = await resolve_full_uuids(prefixes, group_id)
        cited_uuids.update(prefix_map.values())
        if prefix_map:
            await track_referenced_batch(list(prefix_map.values()))
        logger.debug("Turn %d: extracted %d citations", turn, len(prefix_map))
    return cited_uuids


def build_tool_call(tc: Any) -> ToolCall:
    """Extract ToolCall from various formats."""
    return ToolCall(
        id=tc.id if hasattr(tc, "id") else tc.get("id", ""),
        name=tc.name if hasattr(tc, "name") else tc.get("name", ""),
        input=tc.input if hasattr(tc, "input") else tc.get("input", {}),
    )


def append_tool_messages(
    messages: list[Message], content: str, tool_results: list[ToolResult]
) -> None:
    """Append assistant and tool result messages to conversation."""
    messages.append(Message(role="assistant", content=content))
    tool_result_content = "\n".join(
        f"Tool '{r.tool_use_id}' result: {r.content}" for r in tool_results
    )
    messages.append(
        Message(
            role="user",
            content=f"Tool execution results:\n{tool_result_content}\n\nContinue based on these results.",
        )
    )


async def execute_tools_gemini(
    tool_calls: list[Any],
    handler: Any,
    result: AgentResult,
    turn: int,
    progress_callback: Any | None,
    log_tool_call_fn: Any,
    log_tool_result_fn: Any,
) -> list[ToolResult]:
    """Execute tool calls and return results."""
    tool_results: list[ToolResult] = []
    for tc in tool_calls:
        tool_call = build_tool_call(tc)
        log_tool_call_fn(result.agent_id, turn, tool_call.name, tool_call.input)

        await emit_progress(
            result,
            turn,
            "tool_use",
            f"Executing tool: {tool_call.name}",
            progress_callback,
            tool_calls=[{"name": tool_call.name, "input": tool_call.input}],
        )

        tool_result = await handler.execute(tool_call)
        tool_results.append(tool_result)
        log_tool_result_fn(result.agent_id, turn, tool_call.name, tool_result.content)

    return tool_results
