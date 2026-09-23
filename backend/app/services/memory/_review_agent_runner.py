"""Historical memory-review receipt helpers and retired batch entry point."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_unified import MemoryReviewRun
from app.services.curator_retirement import curator_unavailable

from ._review_agent_decisions import MemoryReviewBatchResult
from ._review_agent_select import select_memories_due_for_review

DEFAULT_REVIEWER_AGENT = "memory-curator"
DEFAULT_BATCH_LIMIT = 10
DEFAULT_REVIEW_CADENCE_DAYS = 45


def _review_attempt_key(
    *,
    reviewer_identity: str,
    evidence: dict[str, Any],
) -> str:
    from app.services.context_policy import semantic_hash

    stable_evidence = dict(evidence)
    if "coverage" in stable_evidence:
        stable_evidence["coverage"] = {key: value for key, value in stable_evidence["coverage"].items()
            if key != "omitted_sources"}
    return semantic_hash(
        {
            "review_workflow": "memory_batch",
            "reviewer_identity": reviewer_identity,
            "evidence": stable_evidence,
        }
    )


async def _find_matching_attempt(
    db: AsyncSession,
    attempt_key: str,
) -> MemoryReviewRun | None:
    """Find a prior reservation without loading unrelated run history."""
    result = await db.execute(
        select(MemoryReviewRun)
        .where(MemoryReviewRun.metadata_.contains({"attempt": {"key": attempt_key}}))
        .order_by(MemoryReviewRun.started_at.desc())
    )
    for candidate in result.scalars().all():
        if candidate.status == "completed":
            return None
        attempt = (candidate.metadata_ or {}).get("attempt") or {}
        if attempt.get("status") in {"reserved", "in_progress", "failed"}:
            return candidate
        if candidate.status == "failed":
            return candidate
    return None


async def _record_context_review(
    db: AsyncSession,
    *,
    run: MemoryReviewRun,
    sources: list[dict[str, Any]],
    reviewer_agent_slug: str,
    reviewer_model_id: str | None,
    reviewer_identity: str,
    session_id: str | None,
    failure: str | None = None,
    failure_type: str | None = None,
    raw_content: str | None = None,
) -> str | None:
    """Persist the canonical receipt that drives maintenance ingestion."""
    from app.services.context_governance import record

    payload: dict[str, Any] = {
        "review_workflow": "memory_batch",
        "run_id": str(run.id),
        "attempt_key": (run.metadata_ or {}).get("attempt", {}).get("key"),
        "sources": sources,
        "reviewer_identity": reviewer_identity,
        "reviewer": {
            "agent_slug": reviewer_agent_slug,
            "model": reviewer_model_id,
            "session_id": session_id,
        },
        "coverage": {
            "context": {},
            "workflow": "memory_batch",
            "exact_batch_sources": True,
        },
    }
    if failure is not None:
        payload.update(
            {
                "failure": failure,
                "failure_type": failure_type,
                "failure_evidence": {
                    "run_id": str(run.id),
                    "session_id": session_id,
                    "reviewer_model_id": reviewer_model_id,
                    "raw_content": raw_content,
                },
            }
        )
    receipt_id = await record(db, "context_review", f"agent:{reviewer_agent_slug}", payload)
    run.metadata_ = {**(run.metadata_ or {}), "review_receipt_id": receipt_id}
    return receipt_id


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
    only_incomplete_audit: bool = False,
) -> MemoryReviewBatchResult:
    curator_unavailable()


__all__ = [
    "DEFAULT_BATCH_LIMIT",
    "DEFAULT_REVIEWER_AGENT",
    "DEFAULT_REVIEW_CADENCE_DAYS",
    "run_memory_review_batch",
    "select_memories_due_for_review",
]
