"""Incremental semantic work owned by the existing Memory Curator schedule.

The database lock proves exclusive worker ownership, including after a crash.
Uncertain interrupted calls become handoffs, never silent paid retries. The
configured batch allowance is shared with rolling memory review.
"""
from __future__ import annotations

import uuid
from itertools import product
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context_governance import ContextMaintenanceItem
from app.services.context_maintenance import ACTIVE_STATES, maintenance_event
from app.services.context_policy import ContextPolicy, policy_match, semantic_hash
from app.services.runtime_context import CanonicalContextDeliveryRequest

WORKER_ACTOR = "system:context-curator"


def review_context(item: ContextMaintenanceItem, assigned_slug: str | None = None) -> CanonicalContextDeliveryRequest | None:
    """Choose a real co-applicable context, without claiming exhaustive coverage."""
    policies = [ContextPolicy.model_validate(s["policy"]) for s in item.sources if s.get("policy") and s.get("owner_agent_id") is None]
    dimensions: dict[str, list[Any]] = {
        "project_id": [None], "agent_slug": [assigned_slug], "consumer_surface": ["codex"],
        "consumer_profile": ["agent_startup"], "task_type": [None], "phase": [None],
    }
    for policy in policies:
        if policy.scope in {"project", "agent"}:
            dimensions["project_id" if policy.scope == "project" else "agent_slug"].extend(policy.targets)
        for singular, plural in (("consumer_surface", "consumer_surfaces"), ("consumer_profile", "consumer_profiles"), ("agent_slug", "agent_slugs")):
            dimensions[singular].extend(policy.applicability.get(plural, []))
        dimensions["task_type"].extend(policy.task_types)
        dimensions["phase"].extend(policy.phases)
    for key in dimensions:
        dimensions[key] = [item.context[key]] if key in item.context else list(dict.fromkeys(dimensions[key]))
    workflows = [item.context["workflow_ids"]] if item.context.get("workflow_ids") else [[], *[[w] for w in sorted({w for policy in policies for w in policy.workflows})]]
    for values in product(*dimensions.values()):
        for workflow_ids in workflows:
            context = CanonicalContextDeliveryRequest.model_validate({**dict(zip(dimensions, values, strict=True)), "workflow_ids": workflow_ids, **item.context})
            if all(policy_match(policy, context, requested=True)[0] for policy in policies):
                return context
    return None


async def run_context_maintenance(db: AsyncSession, *, batch_limit: int) -> dict[str, Any]:
    from app.db import async_session
    from app.services.context_maintenance_reconcile import reconcile_maintenance
    from app.services.context_review import ContextReviewRequest, prepare_review, run_review

    # Separate session: review services commit their receipts; ownership must
    # survive those commits without holding source/item locks across inference.
    async with async_session() as ownership:
        acquired = (await ownership.execute(select(func.pg_try_advisory_xact_lock(func.hashtextextended("agent-hub:context-maintenance-worker", 0))))).scalar_one()
        if not acquired:
            return {"status": "already_running", "reviewed_count": 0}
        reconciliation = await reconcile_maintenance(db)
        abandoned = (await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.claim_owner == WORKER_ACTOR).with_for_update())).scalars()
        for item in abandoned:
            item.claim_owner, item.claim_session, item.state = None, None, "pending"
            item.version += 1
            item.detail = {**item.detail, "handoff_needed": True, "interrupted_review": True}
            await maintenance_event(db, item, WORKER_ACTOR, "interrupted_review", {"reason": "Prior worker no longer holds its database lock; inspect provider evidence before retrying."})
        await db.commit()
        candidates = list((await db.execute(select(ContextMaintenanceItem).where(
            ContextMaintenanceItem.state == "pending",
            ~ContextMaintenanceItem.detail.contains({"handoff_needed": True}),
            ~ContextMaintenanceItem.detail.op("?")("background_review_id"),
        ).order_by(ContextMaintenanceItem.created_at, ContextMaintenanceItem.id).limit(batch_limit))).scalars())
        groups: dict[str, tuple[CanonicalContextDeliveryRequest | None, list[str]]] = {}
        from app.models.agent import Agent
        owner_ids = {s["owner_agent_id"] for item in candidates for s in item.sources if s.get("owner_agent_id") is not None}
        owners = {row.id: row.slug for row in (await db.execute(select(Agent.id, Agent.slug).where(Agent.id.in_(owner_ids)))).all()} if owner_ids else {}
        for item in candidates:
            source_owners = {s["owner_agent_id"] for s in item.sources if s.get("owner_agent_id") is not None}
            assigned_slug = owners.get(next(iter(source_owners))) if len(source_owners) == 1 else None
            context = review_context(item, assigned_slug)
            key = semantic_hash(context.model_dump(mode="json")) if context else "unmatched"
            if key not in groups:
                groups[key] = (context, [])
            groups[key][1].append(item.id)
        reviewed = model_calls = 0
        for context, item_ids in groups.values():
            items = list((await db.execute(select(ContextMaintenanceItem).where(
                ContextMaintenanceItem.id.in_(item_ids), ContextMaintenanceItem.state == "pending",
                ContextMaintenanceItem.claim_owner.is_(None),
            ).order_by(ContextMaintenanceItem.id).with_for_update().execution_options(populate_existing=True))).scalars())
            if not items:
                continue
            source_ids = sorted({source_id for item in items for source_id in item.source_keys})
            request = ContextReviewRequest(context=context, source_ids=source_ids, include_neighbors=True, mode="curator", dry_run=False) if context else None
            prepared = await prepare_review(db, request) if request else None
            if context is None or request is None or not prepared or not set(source_ids).issubset({s["source_id"] for s in prepared["sources"]}):
                for item in items:
                    item.detail = {**item.detail, "handoff_needed": True, "background_reason": "No verified common review context; an agent must inspect scope or ownership."}
                    item.version += 1
                    await maintenance_event(db, item, WORKER_ACTOR, "agent_handoff", item.detail)
                await db.commit()
                continue
            claimed_ids = [item.id for item in items]
            for item in items:
                item.state, item.claim_owner, item.claim_session = "claimed", WORKER_ACTOR, str(uuid.uuid4())
                item.version += 1
                await maintenance_event(db, item, WORKER_ACTOR, "review_started", {"context": context.model_dump(mode="json"), "estimated_input_tokens": prepared["estimated_input_tokens"], "batch_items": claimed_ids})
            await db.commit()
            reviewed += len(claimed_ids)
            model_calls += 1
            try:
                result = await run_review(db, request, WORKER_ACTOR)
            except Exception as exc:
                await db.rollback()
                result = {"failure": type(exc).__name__}
            items = list((await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.id.in_(claimed_ids))
                .order_by(ContextMaintenanceItem.id).with_for_update().execution_options(populate_existing=True))).scalars())
            for item in items:
                if item.state not in ACTIVE_STATES or item.claim_owner != WORKER_ACTOR:
                    continue
                downstream = list((await db.execute(select(ContextMaintenanceItem.id).where(
                    ContextMaintenanceItem.evidence_ids.contains([result["review_id"]]),
                    ContextMaintenanceItem.id != item.id,
                    ~ContextMaintenanceItem.id.in_(claimed_ids),
                    ContextMaintenanceItem.state.in_(ACTIVE_STATES),
                ))).scalars()) if result.get("review_id") else []
                item.claim_owner, item.claim_session = None, None
                item.version += 1
                item.detail = {**item.detail, "background_review_id": result.get("review_id"), "handoff_needed": bool(result.get("failure") or result.get("findings"))}
                item.state = "pending" if item.detail["handoff_needed"] else "dismissed"
                if downstream:
                    item.state = "superseded"
                    item.detail = {**item.detail, "handoff_needed": False}
                item.resolution = {"verification": "reviewed_exact_sources; no content change", "review_id": result.get("review_id"), "failure": result.get("failure"), "successor_items": downstream}
                await maintenance_event(db, item, WORKER_ACTOR, "review_completed", item.resolution)
            await db.commit()
        return {"status": "completed", "reviewed_count": reviewed, "model_calls": model_calls, "reconciliation": reconciliation}
