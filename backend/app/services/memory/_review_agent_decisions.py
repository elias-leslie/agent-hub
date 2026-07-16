"""Decision parsing and application for memory review batches."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from ._review_agent_prompt import REVIEW_CHECK_KEYS

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
    checks: dict[str, str] = field(default_factory=dict)
    merge_target_uuid: str | None = None
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
    """Accept semantic compaction or keep using the complete source text.

    Compaction is reviewer-authored.  This validator never crops by character
    count: an invalid candidate is rejected so callers keep the full source.
    The conservative normative signature prevents a compact variant from
    silently weakening repeated ``must``/``never``/``only``-style clauses.
    """
    if not isinstance(candidate, str):
        return None
    compact = " ".join(candidate.split())
    if not compact:
        return None
    if original:
        full = " ".join(original.split())
        if len(compact) >= len(full):
            return None
        original_markers = Counter(
            marker.lower() for marker in _NORMATIVE_PATTERN.findall(full)
        )
        compact_markers = Counter(
            marker.lower() for marker in _NORMATIVE_PATTERN.findall(compact)
        )
        if any(compact_markers[marker] < count for marker, count in original_markers.items()):
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

    recommended_surfaces = item.get("recommended_consumer_surfaces")
    target_surfaces = item.get("target_surfaces") or item.get("target_consumer_surfaces")
    surfaces = recommended_surfaces if isinstance(recommended_surfaces, list) else target_surfaces
    if isinstance(surfaces, list):
        suggested.setdefault(
            "consumer_surfaces",
            [value for value in surfaces if isinstance(value, str)],
        )
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
    merge_target_uuid = item.get("merge_target_uuid") or item.get("superseded_by")
    raw_checks = item.get("checks")
    checks = {
        key: str(raw_checks.get(key))
        for key in REVIEW_CHECK_KEYS
        if isinstance(raw_checks, dict)
        and raw_checks.get(key) in {"pass", "concern", "unknown", "not_applicable"}
    }
    if (
        checks
        and any(value in {"concern", "unknown"} for value in checks.values())
        and review_status != "needs_action"
    ):
        return None
    if (
        checks
        and all(value in {"pass", "not_applicable"} for value in checks.values())
        and review_status != "clean"
    ):
        return None
    if normalized_decision == "merge" and not isinstance(merge_target_uuid, str):
        return None
    return MemoryReviewDecision(
        uuid=uuid,
        decision=normalized_decision,
        review_status=review_status,
        confidence=float(item.get("confidence") or 0.75),
        reason=reason,
        checks=checks,
        merge_target_uuid=(
            str(merge_target_uuid) if isinstance(merge_target_uuid, str) else None
        ),
        suggested_summary=suggested_summary if isinstance(suggested_summary, str) else None,
        compact_content=compact_content,
        suggested_tags=[
            tag.strip()
            for tag in (item.get("suggested_tags") or [])
            if isinstance(tag, str) and tag.strip()
        ],
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
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
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
    decision_uuids = [decision.uuid for decision in decisions]
    if len(decision_uuids) != len(set(decision_uuids)):
        return None
    if set(decision_uuids) != expected_uuids:
        return None
    return decisions


def repair_memory_review_content(
    content: str | None,
    expected_uuids: set[str],
) -> str | None:
    """Deterministically quarantine incomplete per-check reviewer output.

    This is a last-resort repair after a reviewer and its correction/fallback
    failed strict validation. Missing checks become ``unknown`` and any
    concern/unknown forces ``needs_action``; the repair can therefore never
    turn uncertain output into a clean review.
    """
    if not content:
        return None
    raw = content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        items = parsed.get("reviews") or parsed.get("decisions")
    else:
        return None
    if not isinstance(items, list):
        return None

    repaired_items: list[dict[str, Any]] = []
    for original_item in items:
        if not isinstance(original_item, dict):
            return None
        item = dict(original_item)
        raw_checks = item.get("checks")
        if not isinstance(raw_checks, dict):
            raw_checks = {}
        item["checks"] = {
            key: (
                raw_checks[key]
                if raw_checks.get(key)
                in {"pass", "concern", "unknown", "not_applicable"}
                else "unknown"
            )
            for key in REVIEW_CHECK_KEYS
        }
        uncertain = any(
            value in {"concern", "unknown"} for value in item["checks"].values()
        )
        item["review_status"] = "needs_action" if uncertain else "clean"
        if not uncertain:
            item["decision"] = "keep"
        repaired_items.append(item)

    repaired = json.dumps({"reviews": repaired_items}, separators=(",", ":"))
    decisions = parse_memory_review_content(repaired, expected_uuids)
    if decisions is None or not review_decisions_have_complete_checks(decisions):
        return None
    return json.dumps(
        {"reviews": [asdict(decision) for decision in decisions]},
        separators=(",", ":"),
    )


def review_decisions_have_complete_checks(
    decisions: list[MemoryReviewDecision] | None,
) -> bool:
    """Return whether every decision contains the complete nine-check audit."""
    return bool(decisions) and all(
        set(decision.checks) == set(REVIEW_CHECK_KEYS) for decision in decisions
    )


__all__ = [
    "MIN_COMPACT_REVIEW_CONTENT_CHARS",
    "MemoryReviewBatchResult",
    "MemoryReviewDecision",
    "_normalize_compact_content",
    "parse_memory_review_content",
    "repair_memory_review_content",
    "review_decisions_have_complete_checks",
]
