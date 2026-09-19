"""Reconcile evidence and deterministic maintenance through the existing schedule."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context_governance import (
    ContextMaintenanceIngest,
    ContextMaintenanceItem,
    ContextRecord,
)
from app.models.memory_unified import Memory
from app.models.runtime_context import RuntimeContextOverride
from app.models.session import Session
from app.services.context_governance import source_rows
from app.services.context_maintenance import (
    REVIEW_KINDS,
    enqueue,
    evidence_identity,
    ingest_review,
    maintenance_event,
)
from app.services.context_policy import semantic_hash, source_revision, source_snapshot
from app.services.memory.budget import count_tokens


async def reconcile_maintenance(db: AsyncSession, *, actor: str = "system:context-maintenance", repair: bool = True) -> dict[str, Any]:
    """No model calls, source rewrites, arbitrary age limits, or repeated paid retries."""
    records = (await db.execute(select(ContextRecord).where(ContextRecord.kind.in_(REVIEW_KINDS),
        ~select(ContextMaintenanceIngest.record_id).where(ContextMaintenanceIngest.record_id == ContextRecord.id).exists())
        .order_by(ContextRecord.created_at, ContextRecord.id))).scalars()
    ingested = 0
    for record in records:
        await ingest_review(db, record)
        ingested += 1
    rows = await source_rows(db)
    current = {(snapshot["source_type"], snapshot["source_id"]): {**snapshot, "revision": source_revision(row)}
               for row in rows for snapshot in [source_snapshot(row)]}
    items = list((await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.state != "superseded")
        .order_by(ContextMaintenanceItem.id).with_for_update())).scalars())
    superseded = released = 0
    for item in items:
        expected = item.resolution.get("verified_sources") or evidence_identity(item.sources)
        changed = [source for source in expected if source["source_type"] in {"prompt", "memory"}
            and current.get((source["source_type"], source["source_id"]), {}).get("revision") != source["revision"]]
        if changed:
            item.state, item.version = "superseded", item.version + 1
            item.claim_owner, item.claim_session = None, None
            await maintenance_event(db, item, actor, "evidence_changed", {"previous_resolution": item.resolution})
            for previous in changed:
                source = current.get((previous["source_type"], previous["source_id"]))
                if source and source["enabled"]:
                    await enqueue(db, kind="review_due", sources=[source], context={},
                        summary=f"Review evidence changed for {source['name'] or source['source_id']}.",
                        recommendation="Reassess the changed source in the current task context; earlier findings are retained as superseded.",
                        detail={"predecessor_id": item.id})
            superseded += 1
            continue
        if item.claim_session:
            session = await db.get(Session, item.claim_session)
            if session is not None and session.status in {"completed", "failed"}:
                item.claim_owner, item.claim_session = None, None
                item.state = "waiting_owner" if item.state == "waiting_owner" else "pending"
                item.version += 1
                await maintenance_event(db, item, actor, "closed_session_released", {"session_id": session.id, "status": session.status})
                released += 1
    # Source-level deterministic checks operate on actual metadata, not LLM claims.
    identical: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source = current[("memory", str(row.id)) if isinstance(row, Memory) else ("prompt", row.slug)]
        if not source["enabled"] or source["owner_agent_id"] is not None:
            continue
        if isinstance(row, Memory) and row.token_count != count_tokens(row.content):
            await enqueue(db, kind="token_count", sources=[source], context={},
                summary=f"Stored token count is stale for {source['name'] or source['source_id']}.",
                recommendation="Recompute the derived count from unchanged canonical content.")
        if source["policy"]["format"] != "full" and not (source["summary"] or source["compact_content"]):
            await enqueue(db, kind="missing_short_form", sources=[source], context={},
                summary=f"{source['name'] or source['source_id']} requests a short form that does not exist.",
                recommendation="Assess whether full disclosure is appropriate or write a faithful approved short form. Full content remains the fallback.")
        identical[semantic_hash({"content": " ".join(source["content"].split()), "policy": source["policy"]})].append(source)
    for sources in identical.values():
        if len(sources) > 1:
            await enqueue(db, kind="duplicate", sources=sources, context={},
                summary="Identical text has the same scope and disclosure policy in multiple sources.",
                recommendation="Check ownership, references and intent before consolidating; identical text alone does not authorize deletion.")
    placements = (await db.execute(select(RuntimeContextOverride))).scalars()
    for placement in placements:
        if (placement.source_type, placement.source_id) not in current:
            snapshot = {key: getattr(placement, key) for key in ("id", "source_type", "source_id", "consumer_profile", "project_id", "mode", "enabled", "position", "tier_override", "note")}
            await enqueue(db, kind="dangling_placement", sources=[], context={"consumer_profile": placement.consumer_profile, "project_id": placement.project_id},
                summary="A context placement refers to a source that no longer exists.",
                recommendation="Remove the ineffective placement through canonical change history.", detail={"placement": snapshot})
    await db.flush()
    repaired, failed = [], []
    if repair:
        from app.services.context_maintenance_actions import repair_item
        mechanical = list((await db.execute(select(ContextMaintenanceItem).where(
            ContextMaintenanceItem.state == "pending", ContextMaintenanceItem.kind.in_(["token_count", "dangling_placement"])).order_by(ContextMaintenanceItem.id).with_for_update())).scalars())
        for item in mechanical:
            if item.detail.get("automatic_attempt_failed"):
                continue
            item_id = item.id
            try:
                async with db.begin_nested():
                    resolution = await repair_item(db, item, actor)
                    item.state, item.version = "resolved", item.version + 1
                    item.resolution = {**resolution, "verified_sources": evidence_identity(item.sources)}
                    await maintenance_event(db, item, actor, "automatic_repair", item.resolution)
                repaired.append(item_id)
            except Exception as exc:
                # Retain failure for an agent to investigate. The schedule will
                # not keep repeating the same failed operation without new input.
                item = (await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.id == item_id)
                    .execution_options(populate_existing=True))).scalar_one()
                item.detail = {**item.detail, "automatic_attempt_failed": type(exc).__name__, "handoff_needed": True}
                item.version += 1
                await maintenance_event(db, item, actor, "repair_failed", {"error_type": type(exc).__name__})
                failed.append(item_id)
    await db.flush()
    return {"ingested_reviews": ingested, "superseded": superseded, "released_closed_sessions": released,
            "repaired": repaired, "failed": failed, "model_calls": 0}
