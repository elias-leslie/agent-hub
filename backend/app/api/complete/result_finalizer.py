"""Result finalization for completion API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.context_tracker import log_token_usage
from app.services.events import publish_complete
from app.services.session_live_activity import mark_session_terminal_state
from app.services.token_counter import estimate_cost

from .session_manager import apply_execution_metadata, update_provider_metadata

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Session as DBSession

logger = logging.getLogger(__name__)


async def finalize_completion_result(
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    requested_model: str,
    effective_model: str,
    total_input_tokens: int,
    total_output_tokens: int,
    is_new_session: bool,
    final_result: Any | None = None,
    project_id: str | None = None,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
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
    # Log token usage and publish completion
    apply_execution_metadata(
        session,
        requested_model=requested_model,
        effective_model=effective_model,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
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
        session.status = "completed"
    mark_session_terminal_state(
        session,
        phase="completed",
        status="completed",
        summary="Execution completed",
        termination_reason=None,
    )

    await db.commit()
