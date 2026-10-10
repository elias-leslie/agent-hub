"""Canonical maintenance work and attention, independent of delivery transport.

Reading and previewing never consume attention. A claim coordinates work; a
finding grants no authority to change instructions or contact the owner.
Automatic maintenance, technical recovery dispatch and reconciliation belonged
to the retired Memory Curator workflow; their entry points remain so historical
callers get an explicit 410.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context_governance import (
    ContextMaintenanceAttention,
    ContextMaintenanceItem,
    ContextRecord,
)
from app.models.memory_unified import MemoryReviewRun
from app.services.context_policy import ContextPolicy, policy_match, semantic_hash

ACTIVE_STATES = ("pending", "claimed", "waiting_owner", "deferred")


def evidence_identity(sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    return sorted(({key: source[key] for key in ("source_type", "source_id", "revision")} for source in sources),
                  key=lambda source: (source["source_type"], source["source_id"]))


def item_snapshot(row: ContextMaintenanceItem, *, details: bool = True) -> dict[str, Any]:
    result = {key: getattr(row, key) for key in ("id", "kind", "state", "version", "summary", "recommendation", "source_keys", "context", "claim_owner", "claim_session", "decision", "resolution")}
    result.update(created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat())
    result["handoff_needed"] = row.state in ACTIVE_STATES and bool(row.detail.get("handoff_needed"))
    if details:
        result.update(sources=row.sources, evidence_ids=row.evidence_ids, detail=row.detail)
    work = row.detail.get("technical_work")
    result["technical_work"] = {key: work.get(key) for key in ("task_id", "status", "task_owned", "error")} if work else None
    return result


async def maintenance_event(db: AsyncSession, row: ContextMaintenanceItem, actor: str, action: str, evidence: dict[str, Any]) -> None:
    from app.services.context_governance import record
    await record(db, "maintenance", actor, {"item_id": row.id, "action": action, "state": row.state,
        "version": row.version, "sources": evidence_identity(row.sources), "evidence": evidence})


def relevant(row: ContextMaintenanceItem, context: Any, *, assigned_prompts: set[str] | None = None) -> bool:
    for key, value in row.context.items():
        actual = getattr(context, key, None)
        if isinstance(value, list):
            if not set(value).issubset(actual or []):
                return False
        elif actual != value:
            return False
    for source in row.sources:
        if source["source_type"] == "prompt" and not context.include_prompts:
            return False
        if source["source_type"] == "memory" and not context.include_memories:
            return False
        if source["source_type"] == "memory" and source["source_id"] in context.exclude_memory_uuids:
            return False
        if (source.get("policy") or {}).get("scope") == "global" and not context.include_global:
            return False
        if source.get("owner_agent_id") is not None:
            if source["source_id"] not in (assigned_prompts or set()):
                return False
        elif source.get("policy") and not policy_match(ContextPolicy.model_validate(source["policy"]), context, requested=True)[0]:
            return False
    return bool(row.sources or row.detail.get("placement"))


async def relevant_items(db: AsyncSession, context: Any, *, include_closed: bool = False) -> list[ContextMaintenanceItem]:
    assigned: set[str] = set()
    if context.agent_slug:
        from app.models.agent import Agent
        from app.services.prompt_service import get_agent_prompts, get_runtime_excluded_prompt_roles
        agent_id = (await db.execute(select(Agent.id).where(Agent.slug == context.agent_slug))).scalar_one_or_none()
        if agent_id is not None:
            assignments = await get_agent_prompts(db, agent_id, exclude_roles=get_runtime_excluded_prompt_roles(agent_slug=context.agent_slug))
            assigned = {a.prompt.slug for a in assignments if a.prompt.enabled}
    statement = select(ContextMaintenanceItem).order_by(ContextMaintenanceItem.created_at, ContextMaintenanceItem.id)
    if not include_closed:
        statement = statement.where(ContextMaintenanceItem.state.in_(ACTIVE_STATES))
    return [row for row in (await db.execute(statement)).scalars() if relevant(row, context, assigned_prompts=assigned)]


def session_key(context: Any) -> str:
    if not context.session_id:
        raise HTTPException(422, "A session ID is required for acknowledgment and claims")
    return semantic_hash({"surface": context.consumer_surface, "session": context.session_id})


def claimant(context: Any, actor: str) -> str:
    session_key(context)
    return f"{actor}:{context.consumer_surface}:{context.session_id}"


async def attention_summary(db: AsyncSession, context: Any) -> dict[str, Any]:
    rows = await relevant_items(db, context)
    seen = await db.get(ContextMaintenanceAttention, session_key(context)) if context.session_id else None
    acknowledged = seen.acknowledged if seen else {}
    caretaker = context.agent_slug == "memory-curator"
    pending = [r for r in rows if acknowledged.get(r.id, 0) < r.version
        and (not r.claim_session or r.claim_session == context.session_id)
        and (caretaker or r.state == "claimed" or r.state == "waiting_owner"
             or (context.project_id == "agent-hub" and r.detail.get("technical_blocked")))
        and ((r.state == "pending" and (caretaker or r.detail.get("handoff_needed")))
             or (r.state == "claimed" and r.claim_session == context.session_id)
             or (r.state == "waiting_owner" and not r.decision.get("reported")))]
    counts = dict(Counter(row.state for row in pending))
    return {"new_relevant": len(pending), "counts": counts, "items": {r.id: r.version for r in pending},
            "evidence_stage": "available; not proof of native model receipt"}


async def acknowledge(db: AsyncSession, context: Any, versions: dict[str, int]) -> dict[str, Any]:
    key = session_key(context)
    rows = {r.id: r for r in await relevant_items(db, context, include_closed=True)}
    if any(item_id not in rows or rows[item_id].version != version for item_id, version in versions.items()):
        raise HTTPException(409, "Maintenance changed; inspect current items before acknowledging")
    await db.execute(insert(ContextMaintenanceAttention).values(session_key=key, acknowledged={}).on_conflict_do_nothing())
    receipt = (await db.execute(select(ContextMaintenanceAttention).where(ContextMaintenanceAttention.session_key == key).with_for_update())).scalar_one()
    receipt.acknowledged = {**receipt.acknowledged, **versions}
    await db.flush()
    return {"acknowledged": versions, "evidence_stage": "agent acknowledgment; not provider delivery proof"}


async def maintenance_health(db: AsyncSession) -> dict[str, Any]:
    items = list((await db.execute(select(ContextMaintenanceItem).where(
        ContextMaintenanceItem.state.in_(ACTIVE_STATES)))).scalars())
    counts = dict(Counter(item.state for item in items))
    failures = sum(item.kind == "review_failed" or bool(item.detail.get("automatic_attempt_failed"))
        or item.detail.get("recovery_attempt", {}).get("status") == "failed" for item in items)
    technical = [item.detail["technical_work"] for item in items if item.detail.get("technical_work")]
    blocked = sum(bool(item.detail.get("technical_blocked")) for item in items)
    last_success = await db.scalar(select(func.max(ContextRecord.created_at)).where(
        ContextRecord.kind == "context_review", ContextRecord.payload["failure"].as_string().is_(None),
        ContextRecord.payload["reviewer"].as_string().is_not(None)))
    last_memory = (await db.execute(select(MemoryReviewRun).where(MemoryReviewRun.dry_run.is_(False))
        .order_by(MemoryReviewRun.started_at.desc()).limit(1))).scalar_one_or_none()
    return {"state": "retired", "scope": "system", "active_counts": counts,
        "unresolved_failures": failures, "technical_work": len(technical), "technical_blocked": blocked,
        "last_successful_review_at": last_success.isoformat() if last_success else None,
        "last_memory_run": {"id": str(last_memory.id), "status": last_memory.status,
            "reviewed": last_memory.reviewed_count, "failed": last_memory.failed_count,
            "completed_at": last_memory.completed_at.isoformat() if last_memory.completed_at else None} if last_memory else None,
        "schedule_enabled": False, "next_run_at": None,
        "verification": "retained historical findings and review outcomes; automatic maintenance retired"}


async def dispatch_technical_work(
    db: AsyncSession,
    item: ContextMaintenanceItem,
    *,
    reason: str,
) -> dict[str, Any]:
    """Retired: creating SummitFlow technical recovery tasks is unavailable."""
    from app.services.curator_retirement import curator_unavailable

    curator_unavailable()


async def reconcile_technical_work(db: AsyncSession) -> dict[str, Any]:
    """Retired: observing SummitFlow technical recovery tasks is unavailable."""
    from app.services.curator_retirement import curator_unavailable

    curator_unavailable()


async def reconcile_maintenance(db: AsyncSession, *, actor: str = "system:context-maintenance", repair: bool = True) -> dict[str, Any]:
    """Retained historical entry point; automatic maintenance is retired."""
    from app.services.curator_retirement import curator_unavailable

    curator_unavailable()
