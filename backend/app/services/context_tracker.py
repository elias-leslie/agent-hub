"""
Context tracking service for session token usage.

Tracks cumulative token usage per session, calculates context window utilization,
and provides warnings when approaching model limits.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostLog, Session
from app.services.token_counter import get_context_limit

if TYPE_CHECKING:
    from app.models import Message

logger = logging.getLogger(__name__)

# Warning thresholds as percentage of context limit
CONTEXT_WARNING_THRESHOLD = 50  # Note: useful for tracking
CONTEXT_HIGH_THRESHOLD = 75  # Warning
CONTEXT_CRITICAL_THRESHOLD = 90  # Critical warning


@dataclass
class ContextUsage:
    """Context window usage information for a session."""

    used_tokens: int
    limit_tokens: int
    percent_used: float
    remaining_tokens: int
    warning: str | None = None


async def log_token_usage(
    db: AsyncSession,
    session_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float = 0.0,
) -> None:
    """
    Log token usage for a request to the CostLog table.

    Args:
        db: Database session
        session_id: Session ID
        model: Model used
        input_tokens: Input token count
        output_tokens: Output token count
        cost_usd: Estimated cost in USD
    """
    cost_log = CostLog(
        session_id=session_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    db.add(cost_log)
    # Don't commit here - let caller handle transaction


async def get_session_token_totals(
    db: AsyncSession,
    session_id: str,
) -> tuple[int, int]:
    """
    Get cumulative token counts for a session.

    Args:
        db: Database session
        session_id: Session ID

    Returns:
        Tuple of (total_input_tokens, total_output_tokens)
    """
    result = await db.execute(
        select(
            func.coalesce(func.sum(CostLog.input_tokens), 0),
            func.coalesce(func.sum(CostLog.output_tokens), 0),
        ).where(CostLog.session_id == session_id)
    )
    row = result.one()
    return int(row[0]), int(row[1])


async def calculate_context_usage(
    db: AsyncSession,
    session_id: str,
    model: str,
) -> ContextUsage:
    """
    Calculate current context window usage for a session.

    Uses cumulative input tokens from CostLog as the context usage,
    since input tokens include the conversation history.

    Args:
        db: Database session
        session_id: Session ID
        model: Model identifier (for context limit lookup)

    Returns:
        ContextUsage with current stats and any warnings
    """
    total_input, total_output = await get_session_token_totals(db, session_id)

    # The latest input_tokens represents the full context sent
    # (conversation history + new message)
    # Get the most recent request's input tokens as current context size
    result = await db.execute(
        select(CostLog.input_tokens)
        .where(CostLog.session_id == session_id)
        .order_by(CostLog.created_at.desc())
        .limit(1)
    )
    latest_row = result.scalar_one_or_none()
    current_context = latest_row if latest_row else 0

    limit = get_context_limit(model)
    percent = (current_context / limit * 100) if limit > 0 else 0.0
    remaining = max(0, limit - current_context)

    warning = None
    if percent >= CONTEXT_CRITICAL_THRESHOLD:
        warning = f"CRITICAL: Context at {percent:.1f}% capacity. Summarization recommended."
    elif percent >= CONTEXT_HIGH_THRESHOLD:
        warning = f"WARNING: Context at {percent:.1f}% capacity. Consider summarization."
    elif percent >= CONTEXT_WARNING_THRESHOLD:
        warning = f"Note: Context at {percent:.1f}% capacity."

    return ContextUsage(
        used_tokens=current_context,
        limit_tokens=limit,
        percent_used=round(percent, 2),
        remaining_tokens=remaining,
        warning=warning,
    )


async def check_context_before_request(
    db: AsyncSession,
    session_id: str,
    model: str,
    estimated_input_tokens: int,
) -> tuple[bool, ContextUsage]:
    """
    Check if request will exceed context limit.

    Args:
        db: Database session
        session_id: Session ID
        model: Model identifier
        estimated_input_tokens: Estimated tokens for the new request

    Returns:
        Tuple of (can_proceed, context_usage)
    """
    limit = get_context_limit(model)
    percent = (estimated_input_tokens / limit * 100) if limit > 0 else 0.0

    warning = None
    can_proceed = True

    if estimated_input_tokens > limit:
        warning = f"BLOCKED: Request ({estimated_input_tokens:,} tokens) exceeds context limit ({limit:,})"
        can_proceed = False
    elif percent >= CONTEXT_CRITICAL_THRESHOLD:
        warning = f"CRITICAL: Request will use {percent:.1f}% of context. Summarization recommended."
    elif percent >= CONTEXT_HIGH_THRESHOLD:
        warning = f"WARNING: Request will use {percent:.1f}% of context."

    usage = ContextUsage(
        used_tokens=estimated_input_tokens,
        limit_tokens=limit,
        percent_used=round(percent, 2),
        remaining_tokens=max(0, limit - estimated_input_tokens),
        warning=warning,
    )

    return can_proceed, usage


def should_emit_warning(percent_used: float) -> bool:
    """Check if we should emit a warning event at this usage level."""
    return percent_used >= CONTEXT_HIGH_THRESHOLD
