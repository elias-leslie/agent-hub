"""Helper functions and shared models for memory_dashboard endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SummarizeRequest(BaseModel):
    project_id: str | None = Field(default=None, max_length=100, description="Project ID (fallback if session lacks it)")
    branch: str | None = Field(default=None, max_length=200, description="Git branch name for continuity scoping")
    transcript_path: str | None = Field(
        default=None,
        max_length=500,
        description="Path to CC JSONL transcript for richer summaries (e.g., ~/.claude/projects/.../session.jsonl)",
    )
    git_context: str | None = Field(
        default=None,
        max_length=10000,
        description="Raw git log --oneline output captured at session end for commit context enrichment",
    )
    async_dispatch: bool = Field(
        default=False,
        description="Dispatch via Hatchet worker (returns 202). Use for hooks/fire-and-forget.",
    )


async def dispatch_to_hatchet(
    background_tasks: set[Any],
    session_id: str,
    branch: str | None,
    transcript_path: str | None,
    git_context: str | None,
) -> bool:
    """Attempt async dispatch to Hatchet worker. Returns True on success."""
    from app.workflows.summary import SummaryInput, session_summary_task

    try:
        await session_summary_task.aio_run_no_wait(
            input=SummaryInput(
                session_id=session_id,
                branch=branch,
                transcript_path=transcript_path,
                git_context=git_context,
            ),
        )
        return True
    except Exception as e:
        logger.warning("Hatchet dispatch failed for %s, falling back to sync: %s", session_id, e)
        return False


async def apply_ratings_background(background_tasks: set[Any], result: Any) -> None:
    """Fire background tasks for rating tracking after summary generation."""
    import asyncio

    from app.services.memory.usage_tracker import track_harmful_batch, track_helpful_batch

    helpful = [u for u, r in result.ratings.items() if r == "helpful"]
    harmful = [u for u, r in result.ratings.items() if r == "harmful"]
    if helpful:
        rating_task = asyncio.create_task(track_helpful_batch(helpful))
        background_tasks.add(rating_task)
        rating_task.add_done_callback(background_tasks.discard)
    if harmful:
        rating_task = asyncio.create_task(track_harmful_batch(harmful))
        background_tasks.add(rating_task)
        rating_task.add_done_callback(background_tasks.discard)


async def run_sync_summarize(
    background_tasks: set[Any],
    session_id: str,
    project_id: str | None,
    branch: str | None,
    transcript_path: str | None,
    git_context: str | None,
) -> Any:
    """Run synchronous summary generation with background side-effects."""
    import asyncio

    from app.services.memory.session_analysis import analyze_session
    from app.services.memory.summary_generator import generate_session_summary

    try:
        result = await generate_session_summary(
            session_id,
            project_id=project_id,
            branch=branch,
            transcript_path=transcript_path,
            git_context=git_context,
        )
        # Fire transcript-aware session analysis after summary storage so citations,
        # feedback tags, and inline summaries are persisted for dashboard analytics.
        task = asyncio.create_task(analyze_session(session_id, transcript_path=transcript_path))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

        # Apply ratings from the combined LLM call (no separate rating call needed)
        if not result.skipped and result.ratings:
            await apply_ratings_background(background_tasks, result)

        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to generate session summary for %s", session_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate summary: {e}",
        ) from e
