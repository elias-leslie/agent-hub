"""Persistence helpers for memory review decisions."""

from __future__ import annotations

from datetime import datetime

from app.models.memory_unified import Memory

from ._review_agent_decisions import (
    MIN_COMPACT_REVIEW_CONTENT_CHARS,
    MemoryReviewDecision,
    _normalize_compact_content,
)


def _apply_decision(memory: Memory, decision: MemoryReviewDecision, now: datetime) -> None:
    metadata = dict(memory.metadata_ or {})
    review_history = list(metadata.get("review_history") or [])[-4:]
    compact_content = _normalize_compact_content(
        original=memory.content or "",
        candidate=decision.compact_content,
    )
    review_entry = {
        "reviewed_at": now.isoformat(),
        "decision": decision.decision,
        "review_status": decision.review_status,
        "confidence": round(decision.confidence, 3),
        "reason": decision.reason,
        "suggested_summary": decision.suggested_summary,
        "compact_content": compact_content,
        "suggested_tags": decision.suggested_tags,
        "suggested_applicability": decision.suggested_applicability,
        "sensitivity_tier": decision.sensitivity_tier,
    }
    review_history.append(review_entry)
    metadata["last_review"] = review_entry
    metadata["review_history"] = review_history
    metadata["compact_reviewed_at"] = now.isoformat()
    if decision.review_status == "needs_action":
        metadata["review_queue"] = review_entry
    else:
        metadata.pop("review_queue", None)
    if compact_content:
        metadata["compact_content"] = compact_content
        metadata["compact_status"] = "ready"
    else:
        content_length = len(" ".join((memory.content or "").split()))
        metadata["compact_status"] = (
            "not_needed"
            if content_length <= MIN_COMPACT_REVIEW_CONTENT_CHARS
            else "not_provided"
        )
    memory.metadata_ = metadata
    memory.review_status = decision.review_status
    memory.sensitivity_tier = decision.sensitivity_tier
    memory.last_reviewed_at = now
    memory.updated_at = now


__all__ = ["_apply_decision"]
