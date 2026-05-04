"""Decision parsing and application for memory review batches."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

MAX_COMPACT_CONTENT_CHARS = 420
MIN_COMPACT_REVIEW_CONTENT_CHARS = 240
_NORMATIVE_PATTERN = re.compile(
    r"\b(must|never|always|required|require|use|only|do not|don't|cannot|avoid)\b",
    re.IGNORECASE,
)
_CLEAN_DECISION_ALIASES = {"ok", "okay", "pass", "valid", "clean"}
_ACTION_DECISION_ALIASES = {
    "action",
    "fix",
    "needs-action",
    "needs_action",
    "needs review",
    "needs_review",
    "review",
    "reroute",
    "reassign",
    "target",
}
_ARCHIVE_DECISION_ALIASES = {"delete", "remove", "prune", "retire", "archive_or_delete"}


@dataclass
class MemoryReviewDecision:
    """Parsed review-agent decision for one memory."""

    uuid: str
    decision: str
    review_status: str
    confidence: float
    reason: str
    suggested_summary: str | None = None
    compact_content: str | None = None
    suggested_tags: list[str] = field(default_factory=list)
    suggested_applicability: dict[str, Any] = field(default_factory=dict)
    sensitivity_tier: str = "normal"


@dataclass
class MemoryReviewBatchResult:
    """Result of one review batch."""

    run_id: str | None
    status: str
    reviewed_count: int
    needs_action_count: int
    failed_count: int
    reviewer_agent_slug: str
    reviewer_model_id: str | None = None
    session_id: str | None = None
    errors: list[str] = field(default_factory=list)


def _normalize_review_decision(decision: str, review_status: str, has_compact: bool) -> str | None:
    """Normalize reviewer shorthand into persisted decision classes."""
    if decision in {"keep", "retarget", "compress", "archive", "merge", "split"}:
        return decision
    if decision in _CLEAN_DECISION_ALIASES:
        return "keep"
    if decision in _ACTION_DECISION_ALIASES:
        return "retarget"
    if decision in _ARCHIVE_DECISION_ALIASES:
        return "archive"
    compactish = any(token in decision for token in ("compact", "compress", "shorten"))
    targetish = any(token in decision for token in ("target", "route", "scope", "assign"))
    archiveish = any(token in decision for token in ("archive", "delete", "remove", "replace"))
    if archiveish:
        return "archive"
    if compactish and not targetish:
        return "compress"
    if targetish:
        return "retarget"
    if decision.startswith("keep"):
        if review_status == "clean":
            return "keep"
        return "compress" if has_compact else "retarget"
    return None


def _normalize_review_status(review_status: str, decision: str) -> str:
    """Normalize reviewer status shorthand into clean/needs_action."""
    status = review_status.strip().lower()
    if status in {"clean", "needs_action"}:
        return status
    if status in _CLEAN_DECISION_ALIASES:
        return "clean"
    actionish = any(
        token in status
        for token in ("action", "target", "route", "compact", "compress", "archive", "fix")
    )
    if actionish:
        return "needs_action"
    if "clean" in status:
        return "clean"
    if decision == "keep" or decision in _CLEAN_DECISION_ALIASES:
        return "clean"
    return "needs_action"


def _normalize_compact_content(
    *,
    original: str,
    candidate: Any,
) -> str | None:
    """Validate compact prompt text before persisting it."""
    if not isinstance(candidate, str):
        return None
    compact = " ".join(candidate.split())
    if not compact:
        return None
    if len(compact) > MAX_COMPACT_CONTENT_CHARS:
        compact = compact[:MAX_COMPACT_CONTENT_CHARS].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
    if original:
        full = " ".join(original.split())
        if len(compact) >= len(full):
            return None
        original_markers = {marker.lower() for marker in _NORMATIVE_PATTERN.findall(full)}
        compact_markers = {marker.lower() for marker in _NORMATIVE_PATTERN.findall(compact)}
        if original_markers and not original_markers.intersection(compact_markers):
            return None
    return compact


def _resolve_review_uuid(item: dict[str, Any], expected_uuids: set[str], prefixes: dict[str, str | None]) -> str | None:
    uuid = str(item.get("uuid") or item.get("uuid8") or "")
    raw_uuid8 = str(item.get("uuid8") or "")
    if uuid not in expected_uuids and len(uuid) == 8:
        uuid = prefixes.get(uuid) or uuid
    if uuid not in expected_uuids and raw_uuid8:
        uuid = prefixes.get(raw_uuid8[:8]) or uuid
    return uuid if uuid in expected_uuids else None


def _review_status_and_decision(item: dict[str, Any]) -> tuple[str, str] | None:
    decision = str(item.get("decision") or "").strip().lower()
    review_status = str(item.get("review_status") or "")
    needs_action_flag = item.get("needs_action")
    if not review_status and isinstance(needs_action_flag, bool):
        review_status = "needs_action" if needs_action_flag else "clean"
    if decision in {"clean", "needs_action"} and not review_status:
        review_status = decision
        decision = "keep" if review_status == "clean" else "retarget"
    elif decision in _CLEAN_DECISION_ALIASES:
        review_status = review_status or "clean"
    elif decision in _ACTION_DECISION_ALIASES or decision in _ARCHIVE_DECISION_ALIASES:
        review_status = review_status or "needs_action"
    if not review_status:
        review_status = "clean" if decision == "keep" else "needs_action"
    review_status = _normalize_review_status(review_status, decision)
    if not decision:
        decision = "keep" if review_status == "clean" else "retarget"
    return review_status, decision


def _review_reason(item: dict[str, Any], review_status: str) -> str | None:
    reason = str(item.get("reason") or item.get("evidence") or item.get("rationale") or "").strip()
    issues = item.get("issues") or item.get("reasons")
    if not reason and isinstance(issues, list):
        reason = "; ".join(str(issue).strip() for issue in issues if str(issue).strip())
    if not reason and review_status == "clean":
        reason = "No issues reported."
    return reason if reason else None


def _suggested_applicability(item: dict[str, Any]) -> dict[str, Any]:
    for key in ("suggested_applicability", "applicability", "assignment", "targeting"):
        if isinstance(item.get(key), dict):
            suggested = dict(item[key])
            break
    else:
        suggested = {}

    recommendations = {
        "scope": item.get("recommended_scope"),
        "scope_id": item.get("recommended_scope_id"),
        "context_kind": item.get("recommended_context_kind"),
        "tier": item.get("recommended_tier"),
    }
    for key, value in recommendations.items():
        if isinstance(value, str):
            suggested.setdefault(key, value)

    recommended_profiles = item.get("recommended_consumer_profiles")
    target_consumers = (
        item.get("target_consumers")
        or item.get("target_consumer_profiles")
        or item.get("routing")
    )
    profiles = recommended_profiles if isinstance(recommended_profiles, list) else target_consumers
    if isinstance(profiles, list):
        suggested.setdefault("consumer_profiles", [value for value in profiles if isinstance(value, str)])
    return suggested


def _decision_from_item(
    item: dict[str, Any],
    expected_uuids: set[str],
    prefixes: dict[str, str | None],
) -> MemoryReviewDecision | None:
    uuid = _resolve_review_uuid(item, expected_uuids, prefixes)
    if not uuid:
        return None
    status_decision = _review_status_and_decision(item)
    if status_decision is None:
        return None
    review_status, decision = status_decision
    reason = _review_reason(item, review_status)
    if review_status not in {"clean", "needs_action"} or not reason:
        return None
    compact_content = _normalize_compact_content(
        original="",
        candidate=(
            item.get("compact_content")
            or item.get("suggested_compact_content")
            or item.get("prompt_content")
            or item.get("compressed_content")
        ),
    )
    normalized_decision = _normalize_review_decision(decision, review_status, compact_content is not None)
    if normalized_decision is None:
        return None
    sensitivity_tier = str(item.get("sensitivity_tier") or "normal")
    if sensitivity_tier not in {"normal", "personal", "confidential"}:
        sensitivity_tier = "normal"
    suggested_summary = item.get("suggested_summary")
    return MemoryReviewDecision(
        uuid=uuid,
        decision=normalized_decision,
        review_status=review_status,
        confidence=float(item.get("confidence") or 0.75),
        reason=reason[:500],
        suggested_summary=suggested_summary if isinstance(suggested_summary, str) else None,
        compact_content=compact_content,
        suggested_tags=[
            tag.strip()
            for tag in item.get("suggested_tags", [])
            if isinstance(tag, str) and tag.strip()
        ][:12],
        suggested_applicability=_suggested_applicability(item),
        sensitivity_tier=sensitivity_tier,
    )


def parse_memory_review_content(
    content: str | None,
    expected_uuids: set[str],
) -> list[MemoryReviewDecision] | None:
    """Parse review-agent JSON into decisions."""
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        review_items = parsed
    elif isinstance(parsed, dict):
        review_items = parsed.get("reviews")
        if not isinstance(review_items, list):
            review_items = parsed.get("decisions")
    else:
        return None
    if not isinstance(review_items, list):
        return None

    prefixes: dict[str, str | None] = {}
    for expected_uuid in expected_uuids:
        prefix = expected_uuid[:8]
        prefixes[prefix] = expected_uuid if prefix not in prefixes else None

    decisions: list[MemoryReviewDecision] = []
    for item in review_items:
        if not isinstance(item, dict):
            return None
        decision = _decision_from_item(item, expected_uuids, prefixes)
        if decision is None:
            return None
        decisions.append(decision)
    return decisions


__all__ = [
    "MIN_COMPACT_REVIEW_CONTENT_CHARS",
    "MemoryReviewBatchResult",
    "MemoryReviewDecision",
    "_normalize_compact_content",
    "parse_memory_review_content",
]
