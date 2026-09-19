"""Claimed maintenance actions use canonical edits and verify actual delivery."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context_governance import ContextMaintenanceItem, ContextRecord
from app.models.memory_unified import Memory
from app.models.runtime_context import RuntimeContextOverride
from app.services.context_governance import (
    ContextDraft,
    PlacementEdit,
    apply_draft,
    get_source,
    placement_snapshot,
)
from app.services.context_maintenance import (
    ACTIVE_STATES,
    acknowledge,
    attention_summary,
    claimant,
    item_snapshot,
    maintenance_event,
    relevant_items,
)
from app.services.context_policy import lock_placement_layer, semantic_hash, source_revision
from app.services.memory.budget import count_tokens
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    build_canonical_context_delivery,
)


class OwnerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    options: list[str] = Field(default_factory=list)


class MaintenanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["list", "inspect", "acknowledge", "claim", "release", "recover", "defer", "resume", "dismiss", "escalate", "reported", "answer", "repair", "apply", "resolve", "review", "reconcile"] = "list"
    context: CanonicalContextDeliveryRequest
    item_id: str | None = None
    expected_version: int | None = None
    reason: str = ""
    evidence: str = ""
    decision: OwnerDecision | None = None
    draft: ContextDraft | None = None
    change_id: str | None = None
    versions: dict[str, int] = Field(default_factory=dict)
    include_closed: bool = False
    include_background: bool = False
    review_mode: Literal["deterministic", "curator"] = "deterministic"


async def verify_delivery(db: AsyncSession, context: CanonicalContextDeliveryRequest) -> dict[str, Any]:
    delivery = await build_canonical_context_delivery(db, context)
    if delivery.status != "ok" or delivery.required_policy.state != "complete":
        raise HTTPException(409, "Canonical delivery did not verify; maintenance remains open")
    return {"verification": "canonical_generation", "payload_hash": delivery.payload_hash,
            "estimated_tokens": delivery.estimated_tokens, "required_policy": delivery.required_policy.model_dump(),
            "native_model_receipt": "not observed"}


async def repair_item(db: AsyncSession, row: ContextMaintenanceItem, actor: str) -> dict[str, Any]:
    context = CanonicalContextDeliveryRequest.model_validate({"consumer_surface": "agent_runtime", **row.context})
    if row.kind == "token_count":
        source = row.sources[0]
        memory = await get_source(db, source["source_type"], source["source_id"], lock=True)
        if not isinstance(memory, Memory) or source_revision(memory) != source["revision"]:
            raise HTTPException(409, "Source changed; reconcile before repairing derived data")
        before = memory.token_count
        memory.token_count = count_tokens(memory.content)
        await db.flush()
        return {**await verify_delivery(db, context), "derived_before": before, "derived_after": memory.token_count}
    if row.kind == "dangling_placement":
        placement = row.detail["placement"]
        context = context.model_copy(update={"consumer_profile": placement["consumer_profile"], "project_id": placement["project_id"]})
        await lock_placement_layer(db, context.consumer_profile, context.project_id)
        existing = await db.get(RuntimeContextOverride, placement["id"])
        if existing is None:
            return {**await verify_delivery(db, context), "already_removed": True}
        observed = {key: getattr(existing, key) for key in placement}
        if observed != placement:
            raise HTTPException(409, "Placement changed; reconcile before repair")
        try:
            await get_source(db, placement["source_type"], placement["source_id"])
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        else:
            raise HTTPException(409, "The source exists; this placement is no longer dangling")
        before = await placement_snapshot(db, context)
        result = await apply_draft(db, ContextDraft(context=context,
            placements=[PlacementEdit(source_type=placement["source_type"], source_id=placement["source_id"], mode="inherit")],
            expected_placement_revision=semantic_hash(before), reason="Remove a verified dangling context placement"), actor, preview=False)
        return {**await verify_delivery(db, context), "change_id": result["change_id"]}
    raise HTTPException(422, "This finding requires agent assessment; no mechanical repair is defined")


async def handle_maintenance(db: AsyncSession, request: MaintenanceRequest, actor: str, *, operator: bool = False) -> dict[str, Any]:
    if request.action == "reconcile":
        from app.services.context_maintenance_reconcile import reconcile_maintenance
        result = await reconcile_maintenance(db, actor=actor)
        await db.commit()
        return result
    if request.action == "acknowledge":
        result = await acknowledge(db, request.context, request.versions)
        await db.commit()
        return result
    visible = await relevant_items(db, request.context, include_closed=request.include_closed or request.action == "inspect")
    if request.action == "list":
        from app.models.prompt import Prompt
        from app.services.context_maintenance_health import maintenance_health
        guidance = (await db.execute(select(Prompt.content).where(Prompt.slug == "context-maintenance-workflow", Prompt.enabled.is_(True)))).scalar_one_or_none()
        listed = [row for row in visible if request.include_background or request.include_closed or request.context.agent_slug == "memory-curator"
            or row.detail.get("handoff_needed") or row.state == "waiting_owner" or (row.claim_session and row.claim_session == request.context.session_id)]
        return {"items": [item_snapshot(row, details=False) for row in listed], "background_items": len(visible) - len(listed),
                "attention": await attention_summary(db, request.context),
                "health": await maintenance_health(db),
                "guidance": guidance, "guidance_source": "prompt:context-maintenance-workflow" if guidance else None}
    if request.item_id not in {row.id for row in visible}:
        raise HTTPException(404, "Maintenance item is not applicable to this context")
    statement = select(ContextMaintenanceItem).where(ContextMaintenanceItem.id == request.item_id).execution_options(populate_existing=True)
    row = (await db.execute(statement if request.action == "inspect" else statement.with_for_update())).scalar_one()
    if request.action == "inspect":
        records = (await db.execute(select(ContextRecord).where(ContextRecord.id.in_(row.evidence_ids)))).scalars()
        events = (await db.execute(select(ContextRecord).where(ContextRecord.kind == "maintenance",
            ContextRecord.payload["item_id"].as_string() == row.id).order_by(ContextRecord.created_at))).scalars()
        return {"item": item_snapshot(row), "reviews": [{"id": r.id, "kind": r.kind, "payload": r.payload} for r in records],
                "history": [{"id": r.id, "actor": r.actor, "created_at": r.created_at.isoformat(), "payload": r.payload} for r in events]}
    if row.version != request.expected_version:
        raise HTTPException(409, "Maintenance changed; inspect the current version before acting")
    if not request.reason.strip():
        raise HTTPException(422, "Record the reason for this action")
    owner = claimant(request.context, actor)
    if request.action == "claim":
        if row.claim_owner and row.claim_owner != owner:
            raise HTTPException(409, "Another agent owns this item; use its handoff or operator recovery")
        if row.state not in {"pending", "claimed", "waiting_owner"}:
            raise HTTPException(409, "Resume deferred work explicitly before claiming")
        row.claim_owner, row.claim_session = owner, request.context.session_id
        if row.state != "waiting_owner":
            row.state = "claimed"
    elif request.action == "recover":
        if not operator:
            raise HTTPException(403, "Only the operator can recover an unverified abandoned claim; known closed sessions release automatically")
        if not row.claim_owner or row.state not in ACTIVE_STATES:
            raise HTTPException(409, "There is no active claim to recover")
        row.claim_owner, row.claim_session = None, None
        row.state = "waiting_owner" if row.state == "waiting_owner" else "pending"
    elif request.action == "answer":
        if row.state != "waiting_owner" or not row.decision.get("question") or not request.evidence.strip():
            raise HTTPException(422, "Record the actual owner answer and its conversation evidence")
        row.decision = {**row.decision, "answer": request.reason, "answer_evidence": request.evidence,
                        "answer_origin": "operator_ui" if operator else "agent_recorded_user_statement", "recorded_by": actor}
        row.detail = {**row.detail, "handoff_needed": True}
        row.state, row.claim_owner, row.claim_session = "pending", None, None
    elif request.action == "resume":
        if row.state != "deferred":
            raise HTTPException(409, "Only deferred work can be resumed")
        row.state, row.claim_owner, row.claim_session = "pending", None, None
        row.detail = {**row.detail, "handoff_needed": True}
    else:
        if row.claim_owner != owner and not operator:
            raise HTTPException(409, "Claim this item before acting")
        if row.state not in ACTIVE_STATES:
            raise HTTPException(409, "This item is already closed")
        if request.action == "release":
            row.state = "waiting_owner" if row.state == "waiting_owner" else "pending"
            row.claim_owner, row.claim_session = None, None
        elif request.action == "defer":
            row.state, row.claim_owner, row.claim_session = "deferred", None, None
            row.detail = {**row.detail, "deferred_until": "source revision changes or explicit evidence-based resume", "defer_reason": request.reason}
        elif request.action == "escalate":
            if not request.decision or not request.evidence.strip():
                raise HTTPException(422, "Escalation requires a concrete question, recommendation, and evidence")
            row.decision = {**request.decision.model_dump(), "evidence": request.evidence, "reported": False}
            row.state = "waiting_owner"
        elif request.action == "reported":
            if row.state != "waiting_owner" or not request.evidence.strip():
                raise HTTPException(422, "Record the actual conversation anchor after raising the decision")
            row.decision = {**row.decision, "reported": True, "report_evidence": request.evidence, "reported_by": actor}
        elif request.action == "dismiss":
            for source in row.sources:
                if source["source_type"] in {"prompt", "memory"}:
                    current = await get_source(db, source["source_type"], source["source_id"], lock=True)
                    if source_revision(current) != source["revision"]:
                        raise HTTPException(409, "Finding evidence is stale; reconcile and reassess")
            row.resolution = {**await verify_delivery(db, request.context), "assessment": request.reason, "assessor": actor, "kind": "dismissed_after_assessment"}
            row.state = "dismissed"
        elif request.action == "repair":
            row.resolution = await repair_item(db, row, actor)
            row.state = "resolved"
        elif request.action == "apply":
            if request.draft is None or not request.evidence.strip():
                raise HTTPException(422, "Supply the exact canonical draft and the existing authority/evidence for the correction")
            allowed = {(s["source_type"], s["source_id"]) for s in row.sources}
            if any((e.source_type, e.source_id) not in allowed for e in [*request.draft.edits, *request.draft.placements]):
                raise HTTPException(422, "The correction must stay within the reviewed sources")
            if not request.draft.edits and not request.draft.placements:
                raise HTTPException(422, "A correction requires an actual change")
            await lock_placement_layer(db, request.draft.context.consumer_profile, request.draft.context.project_id)
            for source in sorted(row.sources, key=lambda s: (s["source_type"], s["source_id"])):
                if source["source_type"] in {"prompt", "memory"}:
                    current = await get_source(db, source["source_type"], source["source_id"], lock=True)
                    if source_revision(current) != source["revision"]:
                        raise HTTPException(409, "Finding evidence is stale; reconcile and reassess")
            result = await apply_draft(db, request.draft, actor, preview=False)
            row.resolution = {**await verify_delivery(db, request.draft.context), "change_id": result["change_id"],
                "assessment": request.reason, "authority_evidence": request.evidence, "assessor": actor}
            row.state = "resolved"
        elif request.action == "resolve":
            change = await db.get(ContextRecord, request.change_id) if request.change_id else None
            if not change or change.kind != "change":
                raise HTTPException(422, "Resolution needs a canonical change receipt; use dismiss for a false positive")
            revisions = {(s["source_type"], s["source_id"]): s["revision"] for s in row.sources}
            changes = change.payload["changes"]
            matched = [c for c in changes if (c["before"]["source_type"], c["before"]["source_id"]) in revisions]
            if not matched:
                raise HTTPException(422, "The change receipt does not address this finding")
            for c in matched:
                key = (c["before"]["source_type"], c["before"]["source_id"])
                current = await get_source(db, *key, lock=True)
                if revisions[key] != "sha256:" + semantic_hash(c["before"]) or source_revision(current) != c["after_revision"]:
                    raise HTTPException(409, "The change receipt is stale or does not start from the reviewed revision")
            matched_keys = {(c["before"]["source_type"], c["before"]["source_id"]) for c in matched}
            for key, revision in revisions.items():
                if key not in matched_keys and key[0] in {"prompt", "memory"}:
                    current = await get_source(db, *key, lock=True)
                    if source_revision(current) != revision:
                        raise HTTPException(409, "Other evidence changed; reassess the complete finding")
            row.resolution = {**await verify_delivery(db, CanonicalContextDeliveryRequest.model_validate(change.payload["context"])),
                              "change_id": change.id, "assessment": request.reason, "assessor": actor}
            row.state = "resolved"
        elif request.action == "review":
            from app.services.context_review import ContextReviewRequest, run_review
            # Preserve the claim across the provider call; no DB lock is held
            # while waiting. The returned review creates independent proposals.
            source_keys, item_id = list(row.source_keys), row.id
            await db.commit()
            result = await run_review(db, ContextReviewRequest(context=request.context,
                source_ids=source_keys, mode=request.review_mode, dry_run=False), actor)
            return {"review": result, "item_id": item_id, "next": "Inspect the current queue and release your claim if further work remains."}
    row.version += 1
    if row.state in {"resolved", "dismissed"}:
        verified = []
        for source in row.sources:
            if source["source_type"] in {"prompt", "memory"}:
                current = await get_source(db, source["source_type"], source["source_id"])
                verified.append({"source_type": source["source_type"], "source_id": source["source_id"], "revision": source_revision(current)})
        row.resolution = {**row.resolution, "verified_sources": verified}
        row.claim_owner, row.claim_session = None, None
    await db.flush()
    await maintenance_event(db, row, actor, request.action, {"reason": request.reason, "evidence": request.evidence, "resolution": row.resolution, "decision": row.decision})
    await db.commit()
    return {"item": item_snapshot(row)}
