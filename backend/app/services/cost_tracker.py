"""
Cost tracking service for per-request logging.

Logs token usage and estimated costs to the cost_logs table for analytics.
"""

import logging
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostLog
from app.services.token_counter import estimate_cost

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def log_request_cost(
    db: AsyncSession,
    session_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> CostLog:
    """
    Log a request's token usage and estimated cost.

    Args:
        db: Database session
        session_id: Session ID for the request
        model: Model identifier used
        input_tokens: Input token count
        output_tokens: Output token count
        cached_input_tokens: Cached input tokens (for cost reduction)

    Returns:
        Created CostLog entry
    """
    # Calculate cost
    cost = estimate_cost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        cached_input_tokens=cached_input_tokens,
    )

    # Create cost log entry
    cost_log = CostLog(
        session_id=session_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost.total_cost_usd,
    )
    db.add(cost_log)
    # Don't commit - let caller manage transaction

    logger.debug(
        f"Logged cost: session={session_id}, model={model}, "
        f"tokens={input_tokens}+{output_tokens}, cost=${cost.total_cost_usd:.6f}"
    )

    return cost_log
