"""Memory governance snapshot for routing and quality hygiene."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.subtask_types import SUBTASK_TYPES
from app.models import Agent, Memory

from .applicability import (
    applicability_has_exclusions,
    applicability_has_targets,
    normalize_applicability,
    normalize_context_kind,
    normalize_trigger_task_types,
)
from .context_builder_settings import default_agent_memory_config, normalize_memory_config
from .repository import TIER_REVERSE

_STARTUP_CONSUMER_PROFILES = {"agent_startup"}
_WARN_THRESHOLDS = {
    "untargeted_reference_count": 40,
    "oversized_policy_count": 12,
}
_HARD_ISSUE_FIELDS = (
    "policy_with_targeting_count",
    "missing_reference_summary_count",
    "invalid_trigger_task_type_count",
    "startup_profile_agent_target_count",
)
_DELIVERY_ELIGIBLE_TIERS = {"mandate", "guardrail", "reference"}


def _build_issue_label(row: Any, trimmed_summary: str, trimmed_content: str) -> str:
    return (row.name or trimmed_summary or trimmed_content or str(row.id))[:80]


def _top_samples(
    candidates: list[dict[str, Any]],
    *,
    sample_limit: int,
) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda item: (-int(item.get("load_count", 0)), item["label"]),
    )[:sample_limit]


def _raw_trigger_task_types(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip().lower()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


async def collect_memory_governance_snapshot(
    db: AsyncSession,
    *,
    sample_limit: int = 6,
) -> dict[str, Any]:
    """Return current routing-quality evidence for the memory system."""
    memory_result = await db.execute(
        select(
            Memory.id,
            Memory.name,
            Memory.content,
            Memory.summary,
            Memory.context_kind,
            Memory.memory_type,
            Memory.tier,
            Memory.trigger_task_types,
            Memory.applicability,
            Memory.loaded_count,
            Memory.review_status,
        ).where(Memory.status == "active")
    )
    rows = memory_result.all()
    agent_result = await db.execute(
        select(Agent).where(Agent.is_active.is_(True))
    )
    agent_rows = list(agent_result.scalars().all())

    by_context_kind: dict[str, int] = defaultdict(int)
    targeted_count = 0
    explicit_exclusion_count = 0
    untargeted_reference_count = 0
    policy_with_targeting_count = 0
    missing_reference_summary_count = 0
    missing_capability_summary_count = 0
    oversized_policy_count = 0
    alias_trigger_task_type_count = 0
    invalid_trigger_task_type_count = 0
    invalid_trigger_task_type_samples: list[dict[str, Any]] = []
    startup_profile_agent_target_count = 0
    clean_review_count = 0
    pending_review_count = 0
    needs_action_review_count = 0
    invalid_review_status_count = 0
    startup_profile_agent_target_samples: list[dict[str, Any]] = []
    untargeted_reference_candidates: list[dict[str, Any]] = []
    oversized_policy_candidates: list[dict[str, Any]] = []
    canonical_task_types = set(SUBTASK_TYPES)

    for row in rows:
        review_status = str(getattr(row, "review_status", "pending") or "pending")
        if review_status == "clean":
            clean_review_count += 1
        elif review_status == "pending":
            pending_review_count += 1
        elif review_status == "needs_action":
            needs_action_review_count += 1
        else:
            invalid_review_status_count += 1
        tier_name = TIER_REVERSE.get(int(row.tier or 0), "reference")
        context_kind = normalize_context_kind(
            row.context_kind,
            memory_type=row.memory_type,
            tier=row.tier,
        ).value
        applicability = normalize_applicability(row.applicability)
        raw_trigger_types = _raw_trigger_task_types(row.trigger_task_types)
        normalized_trigger_types = normalize_trigger_task_types(raw_trigger_types)
        trimmed_summary = (row.summary or "").strip()
        trimmed_content = (row.content or "").strip()
        delivery_eligible = tier_name in _DELIVERY_ELIGIBLE_TIERS

        by_context_kind[context_kind] += 1

        has_targets = applicability_has_targets(applicability)
        has_exclusions = applicability_has_exclusions(applicability)
        if has_targets:
            targeted_count += 1
        if has_exclusions:
            explicit_exclusion_count += 1

        if delivery_eligible and context_kind in {"reference", "capability"} and not has_targets:
            untargeted_reference_count += 1
            untargeted_reference_candidates.append(
                {
                    "uuid": str(row.id),
                    "label": _build_issue_label(row, trimmed_summary, trimmed_content),
                    "load_count": int(row.loaded_count or 0),
                    "details": f"{context_kind} · loaded {int(row.loaded_count or 0)}",
                }
            )
        if delivery_eligible and context_kind == "policy" and (has_targets or has_exclusions):
            policy_with_targeting_count += 1
        if delivery_eligible and context_kind in {"reference", "capability"} and not trimmed_summary:
            missing_reference_summary_count += 1
            if context_kind == "capability":
                missing_capability_summary_count += 1
        if delivery_eligible and context_kind == "policy" and len(trimmed_content) > 280:
            oversized_policy_count += 1
            oversized_policy_candidates.append(
                {
                    "uuid": str(row.id),
                    "label": _build_issue_label(row, trimmed_summary, trimmed_content),
                    "load_count": int(row.loaded_count or 0),
                    "details": (
                        f"{len(trimmed_content)} chars · loaded {int(row.loaded_count or 0)}"
                    ),
                }
            )
        if (
            delivery_eligible
            and (
            set(applicability.consumer_profiles).intersection(_STARTUP_CONSUMER_PROFILES)
            and applicability.agent_slugs
            )
        ):
            startup_profile_agent_target_count += 1
            if len(startup_profile_agent_target_samples) < sample_limit:
                startup_profile_agent_target_samples.append(
                    {
                        "uuid": str(row.id),
                        "label": _build_issue_label(row, trimmed_summary, trimmed_content),
                        "load_count": int(row.loaded_count or 0),
                        "details": (
                            "startup profile plus agent slug targeting creates dead routes"
                        ),
                    }
                )
        if delivery_eligible and raw_trigger_types != normalized_trigger_types:
            alias_trigger_task_type_count += 1

        invalid_trigger_types = [
            task_type for task_type in normalized_trigger_types if task_type not in canonical_task_types
        ]
        if delivery_eligible and invalid_trigger_types:
            invalid_trigger_task_type_count += 1
            if len(invalid_trigger_task_type_samples) < sample_limit:
                invalid_trigger_task_type_samples.append(
                    {
                        "uuid": str(row.id),
                        "label": _build_issue_label(row, trimmed_summary, trimmed_content),
                        "invalid_types": invalid_trigger_types,
                        "load_count": int(row.loaded_count or 0),
                        "details": f"invalid trigger types: {', '.join(invalid_trigger_types)}",
                    }
                )

    custom_memory_config_agent_count = 0
    project_index_disabled_agent_count = 0
    tool_capabilities_disabled_agent_count = 0
    reference_index_disabled_agent_count = 0
    memory_exclusion_agent_count = 0
    excluded_memory_uuid_count = 0

    for agent in agent_rows:
        raw_memory_config = getattr(agent, "memory_config", None)
        effective_memory_config = (
            normalize_memory_config(raw_memory_config) or default_agent_memory_config()
        )
        if raw_memory_config is not None:
            custom_memory_config_agent_count += 1
        if not bool(effective_memory_config.get("project_index_enabled", True)):
            project_index_disabled_agent_count += 1
        if not bool(effective_memory_config.get("tool_capabilities_enabled", True)):
            tool_capabilities_disabled_agent_count += 1
        if not bool(effective_memory_config.get("reference_index_enabled", True)):
            reference_index_disabled_agent_count += 1
        excluded_uuids = list(effective_memory_config.get("exclude_memory_uuids") or [])
        if excluded_uuids:
            memory_exclusion_agent_count += 1
            excluded_memory_uuid_count += len(excluded_uuids)

    hard_issue_count = sum(
        [
            policy_with_targeting_count,
            missing_reference_summary_count,
            invalid_trigger_task_type_count,
            startup_profile_agent_target_count,
            pending_review_count,
            needs_action_review_count,
            invalid_review_status_count,
        ]
    )
    soft_issue_count = untargeted_reference_count + oversized_policy_count
    issue_count = hard_issue_count + soft_issue_count
    soft_limit_breach_count = sum(
        [
            int(untargeted_reference_count > _WARN_THRESHOLDS["untargeted_reference_count"]),
            int(oversized_policy_count > _WARN_THRESHOLDS["oversized_policy_count"]),
        ]
    )
    if hard_issue_count > 0:
        health_status = "critical"
    elif soft_limit_breach_count > 0:
        health_status = "warn"
    else:
        health_status = "healthy"

    return {
        "active_count": len(rows),
        "clean_review_count": clean_review_count,
        "pending_review_count": pending_review_count,
        "needs_action_review_count": needs_action_review_count,
        "invalid_review_status_count": invalid_review_status_count,
        "review_coverage_count": clean_review_count + needs_action_review_count,
        "health_status": health_status,
        "by_context_kind": dict(sorted(by_context_kind.items())),
        "targeted_count": targeted_count,
        "explicit_exclusion_count": explicit_exclusion_count,
        "untargeted_reference_count": untargeted_reference_count,
        "untargeted_reference_samples": _top_samples(
            untargeted_reference_candidates,
            sample_limit=sample_limit,
        ),
        "policy_with_targeting_count": policy_with_targeting_count,
        "missing_reference_summary_count": missing_reference_summary_count,
        "missing_capability_summary_count": missing_capability_summary_count,
        "oversized_policy_count": oversized_policy_count,
        "oversized_policy_samples": _top_samples(
            oversized_policy_candidates,
            sample_limit=sample_limit,
        ),
        "alias_trigger_task_type_count": alias_trigger_task_type_count,
        "startup_profile_agent_target_count": startup_profile_agent_target_count,
        "startup_profile_agent_target_samples": startup_profile_agent_target_samples,
        "invalid_trigger_task_type_count": invalid_trigger_task_type_count,
        "invalid_trigger_task_type_samples": invalid_trigger_task_type_samples,
        "active_agent_count": len(agent_rows),
        "custom_memory_config_agent_count": custom_memory_config_agent_count,
        "project_index_disabled_agent_count": project_index_disabled_agent_count,
        "tool_capabilities_disabled_agent_count": tool_capabilities_disabled_agent_count,
        "reference_index_disabled_agent_count": reference_index_disabled_agent_count,
        "memory_exclusion_agent_count": memory_exclusion_agent_count,
        "excluded_memory_uuid_count": excluded_memory_uuid_count,
        "hard_issue_count": hard_issue_count,
        "soft_issue_count": soft_issue_count,
        "soft_limit_breach_count": soft_limit_breach_count,
        "issue_count": issue_count,
    }
