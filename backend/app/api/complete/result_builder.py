"""Result building for completion API."""

from __future__ import annotations

from typing import Any

from .error_summary import build_error_summary
from .tool_handlers import AgentProgress


def _resolve_turns(
    progress_log: list[AgentProgress],
    final_result: Any | None,
) -> int:
    """Prefer explicit result turns, else fall back to the highest logged turn."""
    result_turns = getattr(final_result, "turns", None)
    if result_turns:
        return result_turns
    logged_turns = [entry.turn for entry in progress_log if entry.turn > 0]
    if logged_turns:
        return max(logged_turns)
    return 1


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
    turns = _resolve_turns(progress_log, final_result)
    tool_result_summaries = getattr(final_result, "tool_result_summaries", None) or []
    error_summary = getattr(final_result, "error_summary", None) or build_error_summary(
        execution_status=execution_status,
        execution_error=execution_error,
        final_finish_reason=final_finish_reason,
        progress_log=progress_log,
        tool_result_summaries=tool_result_summaries,
    )

    return {
        "content": final_content,
        "model": getattr(final_result, "model_used", None) or model,
        "provider": getattr(final_result, "provider", None) or provider,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "finish_reason": final_finish_reason,
        "session_id": final_session_id,
        "memory_uuids": loaded_memory_uuids,
        "cited_uuids": cited_uuids_list,
        "from_cache": False,
        "cache_metrics": getattr(final_result, "cache_metrics", None),
        "thinking_content": getattr(final_result, "thinking_content", None),
        "thinking_tokens": total_thinking_tokens if total_thinking_tokens else None,
        "tool_calls": getattr(final_result, "tool_calls", None),
        "container": getattr(final_result, "container", None),
        "turns": turns,
        "tool_calls_count": tool_calls_count,
        "status": execution_status,
        "error": execution_error,
        "container_id": current_container_id,
        "progress_log": progress_log,
        "error_summary": error_summary,
        "model_used": getattr(final_result, "model_used", None) or model,
        "fallback_used": bool(getattr(final_result, "fallback_used", False)),
        "requested_model": getattr(final_result, "requested_model", None) or model,
        "requested_provider": getattr(final_result, "requested_provider", None) or provider,
        "fallback_reason": getattr(final_result, "fallback_reason", None),
    }
