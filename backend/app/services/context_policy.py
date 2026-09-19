"""Canonical source applicability and disclosure, independent of UI and transport.

Memory's existing columns remain authoritative. Prompt policy is explicit;
legacy flags are adapted at the boundary rather than becoming a second selector.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.memory.applicability import (
    applicability_matches,
    normalize_applicability,
    normalize_trigger_phases,
    normalize_trigger_task_types,
)
from app.services.memory.memory_models import MemoryApplicability


class ContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["global", "project", "agent", "unassigned"] = "unassigned"
    targets: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    activation: Literal["always", "triggered", "on_demand", "relevant"] = "always"
    task_types: list[str] = Field(default_factory=list)
    phases: list[str] = Field(default_factory=list)
    applicability: dict[str, list[str]] = Field(default_factory=dict)
    required: bool = True
    format: Literal["full", "compact", "summary"] = "full"

    @model_validator(mode="after")
    def validate_policy(self) -> ContextPolicy:
        if self.scope in {"project", "agent"} and not self.targets:
            raise ValueError("Project and agent scope require an explicit target")
        if self.scope in {"global", "unassigned"} and self.targets:
            raise ValueError("This scope cannot have targets")
        if set(self.applicability) - set(MemoryApplicability.model_fields):
            raise ValueError("Unknown consumer targeting field")
        self.applicability = normalize_applicability(self.applicability).model_dump(exclude_defaults=True)
        self.task_types = normalize_trigger_task_types(self.task_types)
        self.phases = normalize_trigger_phases(self.phases)
        if self.required and self.activation == "on_demand":
            raise ValueError("Required applicable rules must be upfront or explicitly triggered; use advisory for on-demand references")
        if self.required and self.format != "full":
            raise ValueError("Required rules must be delivered in full")
        if self.activation == "triggered" and not (self.task_types or self.phases):
            raise ValueError("Triggered disclosure needs a task type or phase")
        return self


def source_policy(row: Any) -> ContextPolicy:
    if hasattr(row, "slug"):
        explicit = getattr(row, "context_policy", None)
        if isinstance(explicit, dict):
            policy = ContextPolicy.model_validate(explicit)
            excluded = list(dict.fromkeys([*policy.applicability.get("exclude_agent_slugs", []), *(row.exclude_agents or [])]))
            if excluded:
                policy.applicability["exclude_agent_slugs"] = excluded
            return policy
        return ContextPolicy(scope="global" if row.is_global else "unassigned")
    from app.services.memory.scope_normalization import normalize_scope_identity
    scope, scope_id = normalize_scope_identity(row.scope, row.scope_id)
    tier = int(row.tier or 3)
    extra = (row.metadata_ or {}).get("disclosure", {})
    return ContextPolicy(
        scope=scope,
        targets=[scope_id] if scope_id and scope != "global" else [],
        workflows=extra.get("workflows", []),
        activation=extra.get("activation", "triggered" if row.trigger_task_types or row.trigger_phases else "always" if tier in {1, 2} else "relevant"),
        task_types=list(row.trigger_task_types or []),
        phases=list(row.trigger_phases or []),
        applicability=dict(row.applicability or {}),
        required=tier in {1, 2},
        format="full" if tier in {1, 2} else row.render_mode or "full",
    )


def policy_match(policy: ContextPolicy, context: Any, *, requested: bool = False) -> tuple[bool, str]:
    workflow = set(policy.workflows).intersection(getattr(context, "workflow_ids", []) or [])
    target = getattr(context, "project_id", None) if policy.scope == "project" else getattr(context, "agent_slug", None)
    scope_matches = policy.scope == "global" or (policy.scope in {"project", "agent"} and target in policy.targets)
    if not (scope_matches or workflow):
        return False, "outside source scope; no explicitly activated workflow"
    if not applicability_matches(
        policy.applicability,
        consumer_surface=context.consumer_surface,
        consumer_profile=context.consumer_profile,
        consumer_agent_slug=getattr(context, "agent_slug", None),
        consumer_tags=getattr(context, "consumer_tags", []),
    ):
        return False, "consumer excluded or does not match targeting"
    if policy.activation == "on_demand" and not requested:
        return False, "available on demand"
    if policy.activation == "triggered":
        if policy.task_types and getattr(context, "task_type", None) not in policy.task_types:
            return False, "task trigger not matched"
        if policy.phases and getattr(context, "phase", None) not in policy.phases:
            return False, "phase trigger not matched"
    return True, "explicit workflow: " + ", ".join(sorted(workflow)) if workflow else f"{policy.scope} scope; {policy.activation}"


def semantic_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def source_snapshot(row: Any) -> dict[str, Any]:
    prompt = hasattr(row, "slug")
    return {
        "source_type": "prompt" if prompt else "memory",
        "source_id": row.slug if prompt else str(row.id),
        "name": row.name or "", "content": row.content,
        "summary": row.description or "" if prompt else row.summary or "",
        "enabled": bool(row.enabled) if prompt else row.status == "active",
        "policy": source_policy(row).model_dump(),
        "owner_agent_id": row.owner_agent_id if prompt else None,
        "memory_tier": None if prompt else row.tier,
        "memory_status": None if prompt else row.status,
        "compact_content": None if prompt else (row.metadata_ or {}).get("compact_content"),
        "authority": row.prompt_type if prompt else {1: "mandate", 2: "guardrail"}.get(row.tier, "reference"),
    }


def source_revision(row: Any) -> str:
    return "sha256:" + semantic_hash(source_snapshot(row))


async def lock_placement_layer(db: Any, profile: str, project: str | None) -> None:
    from sqlalchemy import func, select
    key = int.from_bytes(hashlib.sha256(f"context-placement:{profile}:{project}".encode()).digest()[:8], "big", signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(key)))
