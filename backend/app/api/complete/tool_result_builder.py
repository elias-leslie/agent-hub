"""Result building utilities for tool execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.context_tracker import log_token_usage
from app.services.events import publish_complete
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
    progress_log: list[Any] | None,
) -> ToolExecutionResult:
    """Construct a successful ToolExecutionResult."""
    return ToolExecutionResult(
        content=content,
        model=model,
        provider=provider,
        input_tokens=0,
        output_tokens=estimated_output_tokens,
        finish_reason="end_turn",
        session_id=session_id,
        memory_uuids=loaded_memory_uuids,
        cited_uuids=cited_uuids,
        thinking_content=thinking_content,
        thinking_tokens=thinking_tokens,
        turns=turn or 1,
        tool_calls_count=tool_calls_count,
        status="success",
        progress_log=progress_log or [],
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
    progress_log: list[Any] | None = None,
) -> ToolExecutionResult:
    """Finalize result: track citations, log usage, update session."""
    cited_uuids, estimated_output_tokens = await _track_and_log_usage(
        db, session_id, model, content, loaded_memory_uuids, memory_group_id
    )
    if is_new_session or session.session_type in ("completion",):
        session.status = "completed"
    await db.commit()
    return _build_success_result(
        content, model, provider, session_id, loaded_memory_uuids,
        cited_uuids, estimated_output_tokens, thinking_content,
        thinking_tokens, turn, tool_calls_count, progress_log,
    )


def build_error_result(
    error: Exception,
    model: str,
    provider: str,
    session_id: str,
    loaded_memory_uuids: list[str],
) -> ToolExecutionResult:
    """Build error result."""
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
    )
