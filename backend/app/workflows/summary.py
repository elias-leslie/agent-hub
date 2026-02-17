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
    branch: str | None = None
    is_worktree: bool = False
    transcript_path: str | None = None
    git_context: str | None = None


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

    # Fetch memory contents for combined rating (replaces separate rate_session_memories call)
    memory_contents: dict[str, str] | None = None
    if not input.transcript_path:
        # Only fetch if we have a chance of rating (needs transcript for the LLM call)
        memory_contents = None
    else:
        try:
            memory_contents = await _fetch_memory_contents_for_session(input.session_id)
        except Exception as e:
            logger.warning("Failed to fetch memory contents for %s: %s", input.session_id, e)

    try:
        result = await generate_session_summary(
            input.session_id,
            branch=input.branch,
            is_worktree=input.is_worktree,
            transcript_path=input.transcript_path,
            git_context=input.git_context,
            memory_contents=memory_contents,
        )
    except ValueError as e:
        logger.warning("Cannot summarize session %s: %s", input.session_id, e)
        return {
            "status": "skipped",
            "reason": str(e),
            "session_id": input.session_id,
        }

    ctx.log(f"Summary generated for {input.session_id}: outcome={result.outcome}")

    # Apply ratings from the combined LLM call (replaces separate rate_session_memories)
    rating_info: dict[str, Any] = {}
    if not result.skipped and result.ratings:
        try:
            helpful_uuids = [uuid for uuid, r in result.ratings.items() if r == "helpful"]
            harmful_uuids = [uuid for uuid, r in result.ratings.items() if r == "harmful"]

            if helpful_uuids:
                from app.services.memory.usage_tracker import track_helpful_batch

                await track_helpful_batch(helpful_uuids)

            if harmful_uuids:
                from app.services.memory.usage_tracker import track_harmful_batch

                await track_harmful_batch(harmful_uuids)

            neutral_count = len(result.ratings) - len(helpful_uuids) - len(harmful_uuids)
            rating_info = {
                "memories_rated": len(result.ratings),
                "helpful": len(helpful_uuids),
                "harmful": len(harmful_uuids),
            }
            ctx.log(
                f"Memory rating for {input.session_id}: "
                f"rated={len(result.ratings)} helpful={len(helpful_uuids)} "
                f"harmful={len(harmful_uuids)} neutral={neutral_count}"
            )
        except Exception as e:
            logger.warning("Memory rating application failed for %s: %s", input.session_id, e)

    return {
        "status": "success" if not result.skipped else "skipped",
        "session_id": input.session_id,
        "outcome": result.outcome,
        "summary": result.summary[:200],
        "git_digest": result.git_digest[:200] if result.git_digest else "",
        **rating_info,
    }


async def _fetch_memory_contents_for_session(session_id: str) -> dict[str, str] | None:
    """Fetch loaded memory contents for combined LLM rating.

    Reuses the same logic as memory_rater._fetch_memory_contents but
    is called before the LLM call so ratings are produced inline.
    """
    from app.services.memory.memory_rater import (
        MAX_MEMORIES_TO_RATE,
        MIN_MEMORIES_TO_RATE,
        _fetch_memory_contents,
    )
    from app.services.memory.session_queries import get_memories_loaded

    loaded_uuids = await get_memories_loaded(session_id)
    if len(loaded_uuids) < MIN_MEMORIES_TO_RATE:
        return None

    contents = await _fetch_memory_contents(loaded_uuids[:MAX_MEMORIES_TO_RATE])
    return contents if contents else None
