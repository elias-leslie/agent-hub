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
    transcript_path: str | None = None
    git_context: str | None = None


@hatchet.task(
    name="session-summary",
    input_validator=SummaryInput,
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
    from app.services.memory.session_analysis import analyze_session
    from app.services.memory.summary_generator import generate_session_summary

    # Fetch memory contents for combined rating (replaces separate rate_session_memories call)
    memory_contents: dict[str, str] | None = None
    if input.transcript_path:
        try:
            memory_contents = await _fetch_memory_contents_for_session(input.session_id)
        except Exception as e:
            logger.warning("Failed to fetch memory contents for %s: %s", input.session_id, e)

    skip_reason, result = await _generate_summary(generate_session_summary, input, memory_contents)
    if skip_reason is not None:
        return {
            "status": "skipped",
            "reason": skip_reason,
            "session_id": input.session_id,
        }

    ctx.log(f"Summary generated for {input.session_id}: outcome={result.outcome}")

    analysis_result = await analyze_session(
        input.session_id,
        transcript_path=input.transcript_path,
        git_context=input.git_context,
        branch=input.branch,
    )
    ctx.log(
        f"Session analysis for {input.session_id}: "
        f"credited={analysis_result.citations_credited} "
        f"feedback={analysis_result.feedback_created} "
        f"summary={analysis_result.summary_stored}"
    )

    rating_info = await _apply_memory_ratings(input.session_id, result, ctx)

    return _build_result(input.session_id, result, rating_info, analysis_result)


async def _generate_summary(
    generate_fn: Any,
    input: SummaryInput,
    memory_contents: dict[str, str] | None,
) -> tuple[str | None, Any]:
    """Call generate_session_summary and handle ValueError.

    Returns a tuple of (skip_reason, result). If skip_reason is not None,
    result is None and the task should be skipped.
    """
    try:
        result = await generate_fn(
            input.session_id,
            branch=input.branch,
            transcript_path=input.transcript_path,
            git_context=input.git_context,
            memory_contents=memory_contents,
        )
        return None, result
    except ValueError as e:
        logger.warning("Cannot summarize session %s: %s", input.session_id, e)
        return str(e), None


async def _apply_memory_ratings(
    session_id: str,
    result: Any,
    ctx: Context,
) -> dict[str, Any]:
    """Apply helpful/harmful ratings from the combined LLM call result."""
    if result.skipped or not result.ratings:
        return {}

    try:
        helpful_uuids = [uuid for uuid, r in result.ratings.items() if r == "helpful"]
        harmful_uuids = [uuid for uuid, r in result.ratings.items() if r == "harmful"]

        await _track_ratings(helpful_uuids, harmful_uuids)

        neutral_count = len(result.ratings) - len(helpful_uuids) - len(harmful_uuids)
        ctx.log(
            f"Memory rating for {session_id}: "
            f"rated={len(result.ratings)} helpful={len(helpful_uuids)} "
            f"harmful={len(harmful_uuids)} neutral={neutral_count}"
        )
        return {
            "memories_rated": len(result.ratings),
            "helpful": len(helpful_uuids),
            "harmful": len(harmful_uuids),
        }
    except Exception as e:
        logger.warning("Memory rating application failed for %s: %s", session_id, e)
        return {}


async def _track_ratings(
    helpful_uuids: list[str],
    harmful_uuids: list[str],
) -> None:
    """Persist helpful and harmful memory ratings."""
    if helpful_uuids:
        from app.services.memory.usage_tracker import track_helpful_batch

        await track_helpful_batch(helpful_uuids)

    if harmful_uuids:
        from app.services.memory.usage_tracker import track_harmful_batch

        await track_harmful_batch(harmful_uuids)


def _build_result(
    session_id: str,
    result: Any,
    rating_info: dict[str, Any],
    analysis_result: Any,
) -> dict[str, Any]:
    """Build the final task result dictionary."""
    return {
        "status": "success" if not result.skipped else "skipped",
        "session_id": session_id,
        "outcome": result.outcome,
        "summary": result.summary[:200],
        "git_digest": result.git_digest[:200] if result.git_digest else "",
        "citations_credited": analysis_result.citations_credited,
        "feedback_created": analysis_result.feedback_created,
        "summary_stored": analysis_result.summary_stored,
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
