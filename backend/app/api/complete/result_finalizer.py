"""Result finalization for completion API."""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.models import SessionEventType
from app.services.context_tracker import log_token_usage
from app.services.event_storage import store_child_session_lifecycle_event
from app.services.events import publish_complete
from app.services.session_live_activity import mark_session_completed
from app.services.token_counter import estimate_cost

from .execution_observability import persist_execution_observability
from .session_repo import apply_execution_metadata, update_provider_metadata

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Session as DBSession

logger = logging.getLogger(__name__)


async def _reset_error_session_state(db: AsyncSession, session: DBSession) -> None:
    """Clear failed transactions before touching ORM attributes on an error result path."""
    with suppress(Exception):
        await db.rollback()
    with suppress(Exception):
        await db.refresh(session)


async def finalize_completion_result(
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    requested_model: str,
    effective_model: str,
    provider: str,
    total_input_tokens: int,
    total_output_tokens: int,
    is_new_session: bool,
    final_result: Any | None = None,
    project_id: str | None = None,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
    requested_max_turns: int = 1,
    orchestration_path: str = "single_turn",
    execution_status: str | None = None,
    execution_error: str | None = None,
) -> None:
    """Finalize completion result with token logging and session status.

    Args:
        db: Database session
        session: DB session object
        session_id: Session ID
        requested_model: Requested model identifier
        effective_model: Model that actually executed
        total_input_tokens: Total input tokens used
        total_output_tokens: Total output tokens used
        is_new_session: Whether this is a new session
        final_result: Optional final result with cache metrics
        project_id: Optional project ID for budget tracking
    """
    if execution_status == "error":
        await _reset_error_session_state(db, session)

    # Log token usage and publish completion
    apply_execution_metadata(
        session,
        requested_model=requested_model,
        effective_model=effective_model,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )
    await persist_execution_observability(
        db,
        session,
        session_id,
        provider=provider,
        model_used=effective_model,
        requested_max_turns=requested_max_turns,
        orchestration_path=orchestration_path,
        final_finish_reason=getattr(final_result, "finish_reason", None),
        execution_status=execution_status,
        execution_error=execution_error,
        turns_completed=getattr(final_result, "turns", None),
        tool_calls_count=getattr(final_result, "tool_calls_count", 0) or 0,
        error_summary=getattr(final_result, "error_summary", None),
    )

    cost = estimate_cost(total_input_tokens, total_output_tokens, effective_model)
    await log_token_usage(
        db, session_id, effective_model, total_input_tokens, total_output_tokens, cost.total_cost_usd
    )
    await publish_complete(session_id, total_input_tokens, total_output_tokens, cost.total_cost_usd)

    # NOTE: project budget cost recording is handled by save_and_track() in
    # handler_helpers.py — the canonical finalization path. Do NOT record here
    # to avoid double-counting.

    # Update cache metrics if available
    if final_result and final_result.cache_metrics:
        await update_provider_metadata(
            db,
            session,
            {
                "cache_creation_input_tokens": final_result.cache_metrics.cache_creation_input_tokens,
                "cache_read_input_tokens": final_result.cache_metrics.cache_read_input_tokens,
            },
        )

    # Mark session as completed
    if is_new_session or session.session_type in ("completion",):
        mark_session_completed(
            session,
            summary="Execution completed",
            termination_reason=None,
        )
    else:
        session.health_detail = "completed"
    session.last_activity_at = datetime.now(UTC)
    await store_child_session_lifecycle_event(
        db,
        session,
        SessionEventType.CHILD_SESSION_RESULT,
        summary="Child session completed",
        status="completed",
    )

    await db.commit()
