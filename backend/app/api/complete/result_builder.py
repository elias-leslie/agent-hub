"""Result building for completion API."""

from __future__ import annotations

from typing import Any

from .tool_handlers import AgentProgress


def build_completion_result(
    final_content: str,
    model: str,
    provider: str,
    total_input_tokens: int,
    total_output_tokens: int,
    final_finish_reason: str | None,
    final_session_id: str,
    loaded_memory_uuids: list[str],
    cited_uuids_list: list[str],
    total_thinking_tokens: int | None,
    tool_calls_count: int,
    execution_status: str,
    execution_error: str | None,
    current_container_id: str | None,
    progress_log: list[AgentProgress],
    final_result: Any | None,
) -> dict[str, Any]:
    """Build CompletionInternalResult from execution data.

    Args:
        final_content: Final response content
        model: Model identifier
        provider: Provider name
        total_input_tokens: Total input tokens used
        total_output_tokens: Total output tokens used
        final_finish_reason: Final finish reason
        final_session_id: Session ID
        loaded_memory_uuids: Memory UUIDs that were loaded
        cited_uuids_list: Citation UUIDs
        total_thinking_tokens: Total thinking tokens (if any)
        tool_calls_count: Number of tool calls executed
        execution_status: Execution status
        execution_error: Execution error (if any)
        current_container_id: Container ID (if any)
        progress_log: Progress log entries
        final_result: Final result with additional data

    Returns:
        Dict with all result attributes
    """
    # Calculate turns from progress log
    turns = 1
    if progress_log:
        completed_turns = len([p for p in progress_log if p.status in ("running", "complete", "tool_use")])
        turns = completed_turns // 2 + 1

    return {
        "content": final_content,
        "model": model,
        "provider": provider,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "finish_reason": final_finish_reason,
        "session_id": final_session_id,
        "memory_uuids": loaded_memory_uuids,
        "cited_uuids": cited_uuids_list,
        "from_cache": False,
        "cache_metrics": final_result.cache_metrics if final_result else None,
        "thinking_content": final_result.thinking_content if final_result else None,
        "thinking_tokens": total_thinking_tokens if total_thinking_tokens else None,
        "tool_calls": final_result.tool_calls if final_result else None,
        "container": final_result.container if final_result else None,
        "turns": turns,
        "tool_calls_count": tool_calls_count,
        "status": execution_status,
        "error": execution_error,
        "container_id": current_container_id,
        "progress_log": progress_log,
    }
