"""Outcome-based maintenance health, shared by the worker, agents and UI."""
from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context_governance import ContextMaintenanceItem, ContextRecord
from app.models.memory_unified import MemoryReviewRun
from app.models.persona_scheduled_job import PersonaScheduledJob
from app.services.context_maintenance import ACTIVE_STATES


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
    schedules = list((await db.execute(select(PersonaScheduledJob).where(
        PersonaScheduledJob.payload_type == "memory_review"))).scalars())
    enabled = [job for job in schedules if job.enabled]
    next_runs = [job.next_run_at for job in enabled if job.next_run_at]
    last_regular_failed = bool(last_memory and last_memory.status in {"failed", "blocked"})
    if failures or blocked or last_regular_failed or not enabled:
        state = "needs_attention"
    elif counts.get("waiting_owner"):
        state = "awaiting_owner"
    elif items:
        state = "working"
    else:
        state = "healthy" if last_success else "unverified"
    return {"state": state, "scope": "system", "active_counts": counts,
        "unresolved_failures": failures, "technical_work": len(technical), "technical_blocked": blocked,
        "last_successful_review_at": last_success.isoformat() if last_success else None,
        "last_memory_run": {"id": str(last_memory.id), "status": last_memory.status,
            "reviewed": last_memory.reviewed_count, "failed": last_memory.failed_count,
            "completed_at": last_memory.completed_at.isoformat() if last_memory.completed_at else None} if last_memory else None,
        "schedule_enabled": bool(enabled), "next_run_at": min(next_runs).isoformat() if next_runs else None,
        "verification": "canonical generation and retained review outcomes; native model receipt unobserved"}
