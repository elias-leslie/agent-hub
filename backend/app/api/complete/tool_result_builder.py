"""Result building utilities for tool execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .citation_tracker import track_citations
from .error_summary import build_error_summary
from .tool_models import ToolExecutionResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _track_citations_and_estimate_output(
    db: AsyncSession,
    session_id: str,
    content: str,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
) -> tuple[list[str], int]:
    """Track citations and estimate output tokens. Returns (cited_uuids, output_tokens)."""
    estimated_output_tokens = len(content) // 4
    cited_uuids = await track_citations(
        content, loaded_memory_uuids, memory_group_id, db, session_id
    )
    return cited_uuids, estimated_output_tokens


def _build_success_result(
    content: str,
    model: str,
    provider: str,
    session_id: str,
    estimated_input_tokens: int,
    loaded_memory_uuids: list[str],
    cited_uuids: list[str],
    estimated_output_tokens: int,
    thinking_content: str | None,
    thinking_tokens: int | None,
    turn: int,
    tool_calls_count: int,
    finish_reason: str | None,
    progress_log: list[Any] | None,
    tool_result_summaries: list[str] | None,
    fallback_used: bool,
    fallback_reason: str | None,
) -> ToolExecutionResult:
    """Construct a successful ToolExecutionResult."""
    return ToolExecutionResult(
        content=content,
        model=model,
        provider=provider,
        input_tokens=estimated_input_tokens,
        output_tokens=estimated_output_tokens,
        finish_reason=finish_reason,
        session_id=session_id,
        memory_uuids=loaded_memory_uuids,
        cited_uuids=cited_uuids,
        thinking_content=thinking_content,
        thinking_tokens=thinking_tokens,
        turns=turn or 1,
        tool_calls_count=tool_calls_count,
        status="success",
        progress_log=progress_log or [],
        tool_result_summaries=tool_result_summaries or [],
        error_summary=build_error_summary(
            execution_status="success",
            execution_error=None,
            final_finish_reason=finish_reason,
            progress_log=progress_log or [],
            tool_result_summaries=tool_result_summaries or [],
        ),
        model_used=model,
        requested_model=model,
        requested_provider=provider,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )


async def finalize_result(
    db: AsyncSession,
    session_id: str,
    model: str,
    provider: str,
    content: str,
    estimated_input_tokens: int,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    thinking_content: str | None = None,
    thinking_tokens: int | None = None,
    turn: int = 1,
    tool_calls_count: int = 0,
    finish_reason: str | None = "end_turn",
    progress_log: list[Any] | None = None,
    tool_result_summaries: list[str] | None = None,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
) -> ToolExecutionResult:
    """Finalize result: track citations and build the terminal tool result."""
    cited_uuids, estimated_output_tokens = await _track_citations_and_estimate_output(
        db, session_id, content, loaded_memory_uuids, memory_group_id
    )
    return _build_success_result(
        content, model, provider, session_id, estimated_input_tokens, loaded_memory_uuids,
        cited_uuids, estimated_output_tokens, thinking_content,
        thinking_tokens, turn, tool_calls_count, finish_reason, progress_log,
        tool_result_summaries, fallback_used, fallback_reason,
    )


def build_error_result(
    error: Exception,
    model: str,
    provider: str,
    session_id: str,
    loaded_memory_uuids: list[str],
    *,
    turns: int = 1,
    tool_calls_count: int = 0,
) -> ToolExecutionResult:
    """Build error result, preserving accumulated state when available."""
    return ToolExecutionResult(
        content=f"Error: {error}",
        model=model,
        provider=provider,
        input_tokens=0,
        output_tokens=0,
        finish_reason="error",
        session_id=session_id,
        memory_uuids=loaded_memory_uuids,
        cited_uuids=[],
        status="error",
        error=str(error),
        turns=turns,
        tool_calls_count=tool_calls_count,
        error_summary=build_error_summary(
            execution_status="error",
            execution_error=str(error),
            final_finish_reason="error",
        ),
        model_used=model,
        requested_model=model,
        requested_provider=provider,
    )
