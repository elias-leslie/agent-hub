"""Result building utilities for tool execution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.context_tracker import log_token_usage
from app.services.events import publish_complete
from app.services.token_counter import estimate_cost

from .citation_tracker import track_citations
from .tool_models import ToolExecutionResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Session as DBSession


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
    progress_log: list | None = None,
) -> ToolExecutionResult:
    """Finalize result: track citations, log usage, update session."""
    estimated_output_tokens = len(content) // 4

    # Track citations
    cited_uuids = await track_citations(
        content, loaded_memory_uuids, memory_group_id, db, session_id
    )

    # Log token usage
    cost = estimate_cost(0, estimated_output_tokens, model)
    await log_token_usage(db, session_id, model, 0, estimated_output_tokens, cost.total_cost_usd)
    await publish_complete(session_id, 0, estimated_output_tokens, cost.total_cost_usd)

    # Mark session completed
    if is_new_session:
        session.status = "completed"

    await db.commit()

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
