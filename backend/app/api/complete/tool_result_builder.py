"""Result building utilities for tool execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.services.context_tracker import log_token_usage
from app.services.events import publish_complete
from app.services.session_live_activity import mark_session_completed
from app.services.token_counter import estimate_cost

from .citation_tracker import track_citations
from .tool_models import ToolExecutionResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Session as DBSession


async def _track_and_log_usage(
    db: AsyncSession,
    session_id: str,
    model: str,
    content: str,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
) -> tuple[list[str], int]:
    """Track citations, estimate tokens, and log usage. Returns (cited_uuids, output_tokens)."""
    estimated_output_tokens = len(content) // 4
    cited_uuids = await track_citations(
        content, loaded_memory_uuids, memory_group_id, db, session_id
    )
    cost = estimate_cost(0, estimated_output_tokens, model)
    await log_token_usage(db, session_id, model, 0, estimated_output_tokens, cost.total_cost_usd)
    await publish_complete(session_id, 0, estimated_output_tokens, cost.total_cost_usd)
    return cited_uuids, estimated_output_tokens


def _build_success_result(
    content: str,
    model: str,
    provider: str,
    session_id: str,
    loaded_memory_uuids: list[str],
    cited_uuids: list[str],
    estimated_output_tokens: int,
    thinking_content: str | None,
    thinking_tokens: int | None,
    turn: int,
    tool_calls_count: int,
    finish_reason: str | None,
    progress_log: list[Any] | None,
    fallback_used: bool,
    fallback_reason: str | None,
) -> ToolExecutionResult:
    """Construct a successful ToolExecutionResult."""
    return ToolExecutionResult(
        content=content,
        model=model,
        provider=provider,
        input_tokens=0,
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
        model_used=model,
        requested_model=model,
        requested_provider=provider,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )


async def finalize_result(
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    is_new_session: bool,
    model: str,
    provider: str,
    content: str,
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    thinking_content: str | None = None,
    thinking_tokens: int | None = None,
    turn: int = 1,
    tool_calls_count: int = 0,
    finish_reason: str | None = "end_turn",
    progress_log: list[Any] | None = None,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
) -> ToolExecutionResult:
    """Finalize result: track citations, log usage, update session."""
    cited_uuids, estimated_output_tokens = await _track_and_log_usage(
        db, session_id, model, content, loaded_memory_uuids, memory_group_id
    )
    if is_new_session or session.session_type in ("completion",):
        mark_session_completed(
            session,
            summary="Execution completed",
            termination_reason=None,
        )
    else:
        session.health_detail = "completed"
    session.last_activity_at = datetime.now(UTC)
    await db.commit()
    return _build_success_result(
        content, model, provider, session_id, loaded_memory_uuids,
        cited_uuids, estimated_output_tokens, thinking_content,
        thinking_tokens, turn, tool_calls_count, finish_reason, progress_log,
        fallback_used, fallback_reason,
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
        model_used=model,
        requested_model=model,
        requested_provider=provider,
    )
