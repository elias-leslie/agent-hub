"""Selection and execution flow for memory review batches."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_unified import Memory, MemoryReviewRun

from ._review_agent_apply import _apply_decision
from ._review_agent_decisions import MemoryReviewBatchResult
from ._review_agent_select import select_memories_due_for_review

logger = logging.getLogger(__name__)

DEFAULT_REVIEWER_AGENT = "memory-curator"
DEFAULT_BATCH_LIMIT = 10
DEFAULT_REVIEW_CADENCE_DAYS = 45


def _failed_result(
    run: MemoryReviewRun,
    *,
    reviewer_agent_slug: str,
    reviewer_model_id: str | None,
    session_id: str | None = None,
    failed_count: int,
    error: str,
) -> MemoryReviewBatchResult:
    return MemoryReviewBatchResult(
        run_id=str(run.id),
        status="failed",
        reviewed_count=0,
        needs_action_count=0,
        failed_count=failed_count,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=reviewer_model_id,
        session_id=session_id,
        errors=[error],
    )


async def _idle_result(
    db: AsyncSession,
    run: MemoryReviewRun,
    reviewer_agent_slug: str,
) -> MemoryReviewBatchResult:
    run.status = "idle"
    run.completed_at = datetime.now(UTC)
    await db.flush()
    return MemoryReviewBatchResult(
        run_id=str(run.id),
        status="idle",
        reviewed_count=0,
        needs_action_count=0,
        failed_count=0,
        reviewer_agent_slug=reviewer_agent_slug,
    )


async def _mark_failed_run(
    db: AsyncSession,
    run: MemoryReviewRun,
    *,
    failed_count: int,
    error: str,
    raw_content: str | None = None,
    reviewer_model_id: str | None = None,
) -> None:
    run.status = "failed"
    run.failed_count = failed_count
    run.reviewer_model_id = reviewer_model_id
    run.completed_at = datetime.now(UTC)
    metadata: dict[str, str] = {"error": error}
    if raw_content is not None:
        metadata["raw_content"] = raw_content[:2000]
    run.metadata_ = metadata
    await db.flush()


def _apply_review_decisions(
    memories: list[Memory],
    decisions: list[Any],
    *,
    dry_run: bool,
) -> int:
    needs_action_count = sum(1 for decision in decisions if decision.review_status == "needs_action")
    if not dry_run:
        by_uuid = {decision.uuid: decision for decision in decisions}
        for memory in memories:
            _apply_decision(memory, by_uuid[str(memory.id)], datetime.now(UTC))
    return needs_action_count


async def _completed_result(
    db: AsyncSession,
    run: MemoryReviewRun,
    *,
    decisions: list[Any],
    needs_action_count: int,
    reviewer_agent_slug: str,
    reviewer_model_id: str | None,
    session_id: str | None,
    dry_run: bool,
    force_all: bool,
    only_missing_compact: bool,
) -> MemoryReviewBatchResult:
    run.status = "completed"
    run.reviewed_count = len(decisions)
    run.needs_action_count = needs_action_count
    run.failed_count = 0
    run.reviewer_model_id = reviewer_model_id
    run.completed_at = datetime.now(UTC)
    run.metadata_ = {
        "session_id": session_id,
        "dry_run": dry_run,
        "force_all": force_all,
        "only_missing_compact": only_missing_compact,
        "reviewed_uuids": [decision.uuid for decision in decisions],
    }
    await db.flush()
    return MemoryReviewBatchResult(
        run_id=str(run.id),
        status="completed",
        reviewed_count=len(decisions),
        needs_action_count=needs_action_count,
        failed_count=0,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=reviewer_model_id,
        session_id=session_id,
    )


async def _load_batch_memories(
    db: AsyncSession,
    *,
    batch_limit: int,
    cadence_days: int,
    force_all: bool,
    include_archived: bool,
    only_missing_compact: bool,
) -> list[Memory]:
    return await select_memories_due_for_review(
        db,
        limit=batch_limit,
        cadence_days=cadence_days,
        force_all=force_all,
        include_archived=include_archived,
        only_missing_compact=only_missing_compact,
    )


async def _call_review_for_memories(
    db: AsyncSession,
    *,
    facade: Any,
    memories: list[Memory],
    reviewer_agent_slug: str,
    reviewer_model_id: str | None,
) -> tuple[str, str | None, str | None]:
    governance_snapshot = await facade.collect_memory_governance_snapshot(db)
    prompt = facade.build_memory_review_prompt(memories, governance_snapshot=governance_snapshot)
    return await facade._call_reviewer_agent(
        db,
        reviewer_agent_slug=reviewer_agent_slug,
        prompt=prompt,
        reviewer_model_id=reviewer_model_id,
    )


async def run_memory_review_batch(
    *,
    db: AsyncSession,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    cadence_days: int = DEFAULT_REVIEW_CADENCE_DAYS,
    reviewer_agent_slug: str = DEFAULT_REVIEWER_AGENT,
    reviewer_model_id: str | None = None,
    dry_run: bool = False,
    force_all: bool = False,
    include_archived: bool = False,
    only_missing_compact: bool = False,
) -> MemoryReviewBatchResult:
    """Run one review-agent batch and persist review metadata."""
    from app.services.memory import review_agent as facade

    run = MemoryReviewRun(
        reviewer_agent_slug=reviewer_agent_slug,
        batch_limit=batch_limit,
        dry_run=dry_run,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()

    memories = await _load_batch_memories(
        db,
        batch_limit=batch_limit,
        cadence_days=cadence_days,
        force_all=force_all,
        include_archived=include_archived,
        only_missing_compact=only_missing_compact,
    )
    if not memories:
        return await _idle_result(db, run, reviewer_agent_slug)

    expected_uuids = {str(memory.id) for memory in memories}

    try:
        raw_content, reviewer_model_id, session_id = await _call_review_for_memories(
            db,
            facade=facade,
            memories=memories,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=reviewer_model_id,
        )
    except Exception as exc:
        logger.warning("Memory review agent unavailable", exc_info=True)
        await _mark_failed_run(db, run, failed_count=len(memories), error=str(exc))
        return _failed_result(
            run,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=None,
            failed_count=len(memories),
            error=str(exc),
        )

    decisions = facade.parse_memory_review_content(raw_content, expected_uuids)
    if decisions is None or len(decisions) != len(memories):
        await _mark_failed_run(
            db,
            run,
            failed_count=len(memories),
            error="unparseable_review_response",
            raw_content=raw_content,
            reviewer_model_id=reviewer_model_id,
        )
        return _failed_result(
            run,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=reviewer_model_id,
            session_id=session_id,
            failed_count=len(memories),
            error="unparseable_review_response",
        )

    needs_action_count = _apply_review_decisions(memories, decisions, dry_run=dry_run)
    return await _completed_result(
        db,
        run,
        decisions=decisions,
        needs_action_count=needs_action_count,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=reviewer_model_id,
        session_id=session_id,
        dry_run=dry_run,
        force_all=force_all,
        only_missing_compact=only_missing_compact,
    )


__all__ = [
    "DEFAULT_BATCH_LIMIT",
    "DEFAULT_REVIEWER_AGENT",
    "DEFAULT_REVIEW_CADENCE_DAYS",
    "run_memory_review_batch",
    "select_memories_due_for_review",
]
