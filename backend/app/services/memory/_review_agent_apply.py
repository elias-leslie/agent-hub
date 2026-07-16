"""Persistence helpers for memory review decisions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.models.memory_unified import Memory

from ._review_agent_decisions import (
    MIN_COMPACT_REVIEW_CONTENT_CHARS,
    MemoryReviewDecision,
    _normalize_compact_content,
)
from .repository import TIER_MAP

_AUTO_REMEDIATION_CONFIDENCE = 0.9
_APPLICABILITY_KEYS = {
    "consumer_profiles",
    "consumer_surfaces",
    "agent_slugs",
    "audience_tags",
    "exclude_consumer_profiles",
    "exclude_consumer_surfaces",
    "exclude_agent_slugs",
    "exclude_audience_tags",
}
_CONTEXT_KINDS = {"policy", "reference", "capability", "continuity"}


def _requires_prompt_migration(
    memory: Memory,
    decision: MemoryReviewDecision,
) -> bool:
    """Protect a valid policy until an actually delivered prompt replaces it."""
    if decision.decision != "archive" or memory.context_kind != "policy":
        return False
    if decision.checks.get("appropriateness") != "concern":
        return False
    policy_validity_checks = ("currency", "correctness", "conflict", "lifecycle")
    return all(
        decision.checks.get(key) in {"pass", "not_applicable"}
        for key in policy_validity_checks
    )


def _apply_high_confidence_remediation(
    memory: Memory,
    decision: MemoryReviewDecision,
    now: datetime,
    *,
    active_memory_ids: set[str],
) -> list[str]:
    """Apply only explicit, reversible reviewer remediations backed by confidence."""
    if decision.confidence < _AUTO_REMEDIATION_CONFIDENCE:
        return []
    if "unknown" in decision.checks.values():
        return []

    applied: list[str] = []
    suggested = dict(decision.suggested_applicability or {})
    if decision.decision not in {"archive", "merge"}:
        summary = (decision.suggested_summary or "").strip()
        if summary and summary != (memory.summary or "").strip():
            memory.summary = summary
            applied.append("summary")

        suggested_tags = list(dict.fromkeys(decision.suggested_tags))
        tags = list(dict.fromkeys([*(memory.tags or []), *suggested_tags]))
        if suggested_tags and tags != list(memory.tags or []):
            memory.tags = tags
            applied.append("tags")

    if decision.decision == "retarget":
        scope = suggested.get("scope")
        if scope in {"global", "project", "agent"} and scope != memory.scope:
            memory.scope = scope
            memory.scope_id = None if scope == "global" else suggested.get("scope_id")
            applied.append(f"scope:{scope}")
        elif scope in {"project", "agent"} and suggested.get("scope_id") != memory.scope_id:
            memory.scope_id = suggested.get("scope_id")
            applied.append(f"scope_id:{memory.scope_id}")

        context_kind = suggested.get("context_kind")
        if context_kind in _CONTEXT_KINDS and context_kind != memory.context_kind:
            memory.context_kind = context_kind
            applied.append(f"context_kind:{context_kind}")

        tier = suggested.get("tier")
        if tier in TIER_MAP and TIER_MAP[tier] != memory.tier:
            memory.tier = TIER_MAP[tier]
            memory.memory_type = tier if tier in {"mandate", "guardrail", "reference"} else memory.memory_type
            applied.append(f"authority:{tier}")

        trigger_task_types = suggested.get("trigger_task_types")
        if (
            isinstance(trigger_task_types, list)
            and all(isinstance(value, str) for value in trigger_task_types)
            and trigger_task_types != list(memory.trigger_task_types or [])
        ):
            memory.trigger_task_types = list(dict.fromkeys(trigger_task_types))
            applied.append("trigger_task_types")

        trigger_phases = suggested.get("trigger_phases")
        if (
            isinstance(trigger_phases, list)
            and all(isinstance(value, str) for value in trigger_phases)
            and trigger_phases != list(memory.trigger_phases or [])
        ):
            memory.trigger_phases = list(dict.fromkeys(trigger_phases))
            applied.append("trigger_phases")

        applicability_updates = {
            key: value for key, value in suggested.items() if key in _APPLICABILITY_KEYS
        }
        if applicability_updates:
            applicability = dict(memory.applicability or {})
            applicability.update(applicability_updates)
            if applicability != dict(memory.applicability or {}):
                memory.applicability = applicability
                applied.append("applicability")

    if decision.decision in {"archive", "merge"}:
        if _requires_prompt_migration(memory, decision):
            return applied
        merge_target = decision.merge_target_uuid
        if decision.decision == "merge":
            if not merge_target or merge_target not in active_memory_ids:
                return applied
            memory.superseded_by = UUID(merge_target)
            applied.append(f"superseded_by:{merge_target}")
        memory.status = "archived"
        memory.tier = TIER_MAP["archive"]
        memory.pinned = False
        memory.auto_inject = False
        memory.retired_at = now
        applied.append("archived")

    return applied


def _apply_decision(
    memory: Memory,
    decision: MemoryReviewDecision,
    now: datetime,
    *,
    active_memory_ids: set[str] | None = None,
) -> None:
    metadata = dict(memory.metadata_ or {})
    review_history = list(metadata.get("review_history") or [])[-4:]
    remediation_is_safe = (
        decision.confidence >= _AUTO_REMEDIATION_CONFIDENCE
        and "unknown" not in decision.checks.values()
    )
    compact_content = (
        _normalize_compact_content(
            original=memory.content or "",
            candidate=decision.compact_content,
        )
        if remediation_is_safe
        else None
    )
    review_entry = {
        "reviewed_at": now.isoformat(),
        "decision": decision.decision,
        "review_status": decision.review_status,
        "confidence": round(decision.confidence, 3),
        "reason": decision.reason,
        "checks": decision.checks,
        "suggested_summary": decision.suggested_summary,
        "compact_content": compact_content,
        "suggested_tags": decision.suggested_tags,
        "suggested_applicability": decision.suggested_applicability,
        "sensitivity_tier": decision.sensitivity_tier,
        "prompt_migration_required": _requires_prompt_migration(memory, decision),
    }
    review_entry["applied_remediations"] = _apply_high_confidence_remediation(
        memory,
        decision,
        now,
        active_memory_ids=active_memory_ids or {str(memory.id)},
    )
    if compact_content:
        review_entry["applied_remediations"].append("compact_content")
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
    memory.version = int(getattr(memory, "version", 1) or 1) + 1
    memory.updated_at = now


__all__ = ["_apply_decision"]
