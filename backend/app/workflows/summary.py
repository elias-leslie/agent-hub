"""Session summary workflow."""

from __future__ import annotations

import logging
from typing import Any

from hatchet_sdk import (
    ConcurrencyExpression,
    ConcurrencyLimitStrategy,
    Context,
)
from pydantic import BaseModel

from app.hatchet_app import hatchet

logger = logging.getLogger(__name__)


class SummaryInput(BaseModel):
    session_id: str


@hatchet.task(
    name="session-summary",
    input_validator=SummaryInput,
    execution_timeout="300s",
    retries=3,
    backoff_factor=2.0,
    backoff_max_seconds=300,
    concurrency=ConcurrencyExpression(
        expression="input.session_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def session_summary_task(input: SummaryInput, ctx: Context) -> dict[str, Any]:
    from app.services.memory.summary_generator import generate_session_summary

    try:
        result = await generate_session_summary(input.session_id)
    except ValueError as e:
        logger.warning("Cannot summarize session %s: %s", input.session_id, e)
        return {
            "status": "skipped",
            "reason": str(e),
            "session_id": input.session_id,
        }

    ctx.log(f"Summary generated for {input.session_id}: outcome={result.outcome}")
    return {
        "status": "success" if not result.skipped else "skipped",
        "session_id": input.session_id,
        "outcome": result.outcome,
        "summary": result.summary[:200],
    }
