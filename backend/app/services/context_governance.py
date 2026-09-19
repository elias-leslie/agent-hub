"""Transactional operator controls over the canonical context sources.

A draft uses the actual assembler in a rolled-back savepoint. No alternative
preview renderer or policy store is maintained here.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context_governance import ContextRecord
from app.models.memory_unified import Memory
from app.models.prompt import Prompt
from app.models.runtime_context import RuntimeContextOverride
from app.services.context_policy import (
    ContextPolicy,
    lock_placement_layer,
    policy_match,
    semantic_hash,
    source_revision,
    source_snapshot,
)
from app.services.memory.budget import count_tokens
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    build_canonical_context_delivery,
)


class SourceEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: Literal["prompt", "memory"]
    source_id: str
    expected_revision: str
    name: str | None = None
    content: str | None = None
    summary: str | None = None
    enabled: bool | None = None
    policy: ContextPolicy | None = None
    archive: bool = False
    memory_tier: Literal[1, 2, 3, 4] | None = None
    memory_status: Literal["active", "disabled", "archived", "quarantined", "superseded"] | None = None
    compact_content: str | None = None


class PlacementEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: Literal["prompt", "memory"]
    source_id: str
    mode: Literal["include", "exclude", "inherit"]


class ContextDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: CanonicalContextDeliveryRequest
    edits: list[SourceEdit] = Field(default_factory=list)
    placements: list[PlacementEdit] = Field(default_factory=list)
    expected_placement_revision: str | None = None
    reason: str = "Operator context edit"
    proposal_id: str | None = None


async def source_rows(db: AsyncSession) -> list[Prompt | Memory]:
    return [*list((await db.execute(select(Prompt).order_by(Prompt.slug))).scalars()),
            *list((await db.execute(select(Memory).order_by(Memory.id))).scalars())]


async def get_source(db: AsyncSession, source_type: str, source_id: str, *, lock: bool = False) -> Prompt | Memory:
    if source_type == "prompt":
        statement = select(Prompt).where(Prompt.slug == source_id)
    else:
        try:
            memory_id = uuid.UUID(source_id)
        except ValueError as exc:
            raise HTTPException(422, "Use the complete memory UUID") from exc
        statement = select(Memory).where(Memory.id == memory_id)
    if lock:
        statement = statement.with_for_update()
    row = (await db.execute(statement.execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Source no longer exists: {source_id}")
    return row


async def record(db: AsyncSession, kind: str, actor: str, payload: dict[str, Any]) -> str:
    key = str(uuid.uuid4())
    source_ids = {s["source_id"] for s in payload.get("sources", []) if "source_id" in s}
    source_ids.update(c["before"]["source_id"] for c in payload.get("changes", []))
    if payload.get("source_id"):
        source_ids.add(payload["source_id"])
    if payload.get("source", {}).get("source_id"):
        source_ids.add(payload["source"]["source_id"])
    evidence = ContextRecord(id=key, kind=kind, actor=actor, source_keys=sorted(source_ids), payload=payload)
    db.add(evidence)
    await db.flush()
    from app.services.context_maintenance import ingest_review
    await ingest_review(db, evidence)
    return key


async def placement_snapshot(db: AsyncSession, context: CanonicalContextDeliveryRequest) -> list[dict[str, Any]]:
    rows = (await db.execute(select(RuntimeContextOverride).where(
        RuntimeContextOverride.consumer_profile == context.consumer_profile,
        RuntimeContextOverride.project_id == context.project_id,
    ).order_by(RuntimeContextOverride.source_type, RuntimeContextOverride.source_id))).scalars()
    return [{"source_type": r.source_type, "source_id": r.source_id, "mode": r.mode,
             "enabled": r.enabled, "position": r.position, "note": r.note, "tier_override": r.tier_override} for r in rows]


async def inventory(db: AsyncSession, context: CanonicalContextDeliveryRequest) -> dict[str, Any]:
    from app.services.memory.context_profiles import MemoryConsumerProfile
    delivery = await build_canonical_context_delivery(db, context)
    delivered = {(block.provenance.source_type, block.provenance.source_id): block for block in delivery.blocks}
    excluded = {(block.source_type, block.source_id) for block in (delivery.preview.excluded if delivery.preview else [])}
    rows = await source_rows(db)
    source_ids = [r.slug if isinstance(r, Prompt) else str(r.id) for r in rows]
    reviews = (await db.execute(select(ContextRecord).where(
        ContextRecord.kind.in_(["context_review", "context_screen", "curator_proposal"]),
        ContextRecord.source_keys.op("?|")(array(source_ids)),
    ).order_by(ContextRecord.created_at.desc()))).scalars() if source_ids else []
    latest_reviews: dict[str, tuple[str, str]] = {}
    for review in reviews:
        evidence = review.payload.get("sources", [])
        if review.kind == "curator_proposal":
            evidence = [{**review.payload["source"], "revision": review.payload["revision"]}]
        for source in evidence:
            latest_reviews.setdefault(source["source_id"], (source["revision"], "screened" if review.kind == "context_screen" else "review failed" if review.payload.get("failure") else "proposal available"))
    sources = []
    for row in rows:
        snapshot = source_snapshot(row)
        key = (snapshot["source_type"], snapshot["source_id"])
        match, reason = policy_match(ContextPolicy.model_validate(snapshot["policy"]), delivery.metadata,
                                     requested=snapshot["source_id"] in context.requested_source_ids)
        block = delivered.get(key)
        state = "included" if block else "excluded here" if key in excluded else "eligible, not selected" if match else "not applicable"
        if not snapshot["enabled"]:
            state, reason = "disabled", "source disabled or archived"
        if snapshot["owner_agent_id"] is not None:
            state, reason = "agent owned", "managed by its agent prompt stack"
        revision = source_revision(row)
        reviewed = latest_reviews.get(snapshot["source_id"])
        review_status = (reviewed[1] if reviewed[0] == revision else "stale review") if reviewed else getattr(row, "review_status", None)
        sources.append({**snapshot, "revision": revision, "state": "indexed" if block and block.provenance.disclosure == "index" else state,
                        "reason": block.provenance.reason if block else reason,
                        "tokens": block.estimated_tokens if block else count_tokens(row.content),
                        "rendered": block.content if block else None,
                        "review_status": review_status})
    for block in delivery.blocks:
        if block.provenance.source_type == "computed":
            sources.append({"source_type": "computed", "source_id": block.block_id, "name": block.title,
                "content": block.content, "summary": "Generated by the canonical capability registry",
                "enabled": True, "policy": None, "owner_agent_id": None, "authority": block.authority,
                "revision": block.provenance.source_revision, "state": "included", "reason": block.provenance.reason,
                "tokens": block.estimated_tokens, "rendered": block.content, "review_status": None})
    placements = await placement_snapshot(db, context)
    by_key = {(s["source_type"], s["source_id"]): s for s in sources}
    warnings = []
    for placement in placements:
        source = by_key.get((placement["source_type"], placement["source_id"]))
        if source is None:
            warnings.append({**placement, "reason": "Source no longer exists; remove this dangling placement."})
        elif placement["mode"] == "include" and source["state"] in {"not applicable", "disabled", "agent owned"}:
            warnings.append({**placement, "reason": "Include does not override source eligibility. Review its scope or inherit."})
    return {"sources": sources, "delivery": delivery.model_dump(mode="json"), "placements": placements,
            "profiles": [profile.value for profile in MemoryConsumerProfile],
            "placement_warnings": warnings,
            "placement_revision": semantic_hash(placements),
            "coverage": {"native_system_prompts": "unobservable unless supplied explicitly", "delivery_stage": "generated",
                         "legacy_helpful_counts": "legacy mixed signals; citations previously credited as helpful"}}


async def apply_source_edit(db: AsyncSession, edit: SourceEdit, actor: str, reason: str, *, preview: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    row = await get_source(db, edit.source_type, edit.source_id, lock=True)
    before = source_snapshot(row)
    if source_revision(row) != edit.expected_revision:
        raise HTTPException(409, f"{edit.source_id} changed. Reload and review the new revision.")
    if isinstance(row, Prompt) and row.owner_agent_id is not None:
        raise HTTPException(422, "Edit owned prompts in the agent editor; ownership cannot be changed here")
    policy = edit.policy or ContextPolicy.model_validate(before["policy"])
    if edit.policy is not None and policy.scope == "project":
        from app.core.project_roots import get_registered_project_roots
        roots = await get_registered_project_roots()
        if set(policy.targets) - set(roots):
            raise HTTPException(422, "Choose registered project targets")
    if isinstance(row, Memory) and len(policy.targets) > 1:
        raise HTTPException(422, "A memory has one canonical scope target. Use workflow activation for reuse.")
    if edit.content is not None and not edit.content.strip():
        raise HTTPException(422, "Content cannot be empty")
    if isinstance(row, Prompt):
        if policy.activation == "relevant":
            raise HTTPException(422, "Prompt disclosure uses explicit task triggers or on-demand retrieval")
        if edit.archive:
            raise HTTPException(422, "Prompts can be disabled; archive is a memory lifecycle action")
        if row.prompt_type in {"global_guardrail", "global_mandate"} and not policy.required:
            raise HTTPException(422, "Change authority in the prompt editor before treating a rule as advisory")
        for attr in ("name", "content", "enabled"):
            value = getattr(edit, attr)
            if value is not None:
                setattr(row, attr, value)
        if edit.summary is not None:
            row.description = edit.summary
        row.context_policy = policy.model_dump()
        row.exclude_agents = policy.applicability.get("exclude_agent_slugs", [])
        row.is_global = policy.scope == "global"
        row.boot_eligible = row.is_global and policy.activation == "always"
        if not preview:
            from app.services.prompt_service import record_prompt_revision
            await record_prompt_revision(db, row, action="context_edit", changed_by=actor, change_reason=reason)
    else:
        if policy.scope == "unassigned":
            raise HTTPException(422, "Memories require global, project or agent scope")
        if edit.content is not None and edit.content != row.content:
            from app.services.memory.embedder import get_embedder
            from app.services.memory.episode_validation import EpisodeValidator
            from app.services.memory.fingerprint import content_fingerprint
            EpisodeValidator.validate_content(edit.content, tier="mandate" if policy.required else "reference")
            row.content = edit.content
            row.content_fingerprint = content_fingerprint(row.content)
            # Required for draft retrieval parity as well as committed search.
            row.embedding = await get_embedder().embed(row.content)
            row.metadata_ = {k: v for k, v in (row.metadata_ or {}).items() if k not in {"compact_content", "compact_reviewed_at", "source_compact_validated_at"}}
        if edit.name is not None:
            row.name = edit.name
        if edit.summary is not None:
            row.summary = edit.summary
        if edit.archive:
            row.status = "archived"
        elif edit.enabled is not None:
            row.status = "active" if edit.enabled else "disabled"
        if edit.memory_tier is not None:
            row.tier = edit.memory_tier
        if edit.memory_status is not None:
            row.status = edit.memory_status
        row.scope, row.scope_id = policy.scope, policy.targets[0] if policy.targets else None
        if row.scope != before["policy"]["scope"] or policy.targets != before["policy"]["targets"]:
            from app.services.memory.service import MemoryScope, build_group_id
            row.group_id = build_group_id(MemoryScope(row.scope), row.scope_id)
        row.applicability = policy.applicability
        row.trigger_task_types, row.trigger_phases = policy.task_types, policy.phases
        row.render_mode = policy.format
        if edit.summary is not None and policy.format == "compact":
            row.metadata_ = {**(row.metadata_ or {}), "compact_content": edit.summary}
        if "compact_content" in edit.model_fields_set:
            metadata = dict(row.metadata_ or {})
            if edit.compact_content is None:
                metadata.pop("compact_content", None)
            else:
                metadata["compact_content"] = edit.compact_content
            row.metadata_ = metadata
        if policy.required and row.tier not in {1, 2}:
            row.tier = 1
        elif not policy.required and row.tier in {1, 2}:
            row.tier = 3
        row.metadata_ = {**(row.metadata_ or {}), "disclosure": {"workflows": policy.workflows, "activation": policy.activation}}
        row.version = int(row.version or 1) + 1
        row.token_count = count_tokens(row.content)
        if not preview:
            from app.services.memory._repo_revisions import RevisionRepository
            await RevisionRepository().record_revision(db, row, action="context_edit", changed_by=actor, change_reason=reason)
    await db.flush()
    return before, source_snapshot(row)


async def apply_draft(db: AsyncSession, draft: ContextDraft, actor: str, *, preview: bool, original_placements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    # Use the same lock order as undo: placement layer, then sorted sources.
    await lock_placement_layer(db, draft.context.consumer_profile, draft.context.project_id)
    if draft.proposal_id:
        from app.services.context_review import verify_proposal_sources
        await verify_proposal_sources(db, draft.proposal_id, additional_keys=[(e.source_type, e.source_id) for e in draft.edits])
    changes = []
    keys = [(e.source_type, e.source_id) for e in draft.edits]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, "A draft may edit each source once")
    # Stable locking order prevents concurrent bulk-edit deadlocks.
    for edit in sorted(draft.edits, key=lambda e: (e.source_type, e.source_id)):
        before, after = await apply_source_edit(db, edit, actor, draft.reason, preview=preview)
        changes.append({"before": before, "after": after, "after_revision": "sha256:" + semantic_hash(after)})
    before_placements = await placement_snapshot(db, draft.context)
    if draft.placements:
        await lock_placement_layer(db, draft.context.consumer_profile, draft.context.project_id)
        before_placements = await placement_snapshot(db, draft.context)
        if draft.expected_placement_revision != semantic_hash(before_placements):
            raise HTTPException(409, "Placement rules changed. Reload before saving.")
        for placement in draft.placements:
            if placement.mode != "inherit":
                await get_source(db, placement.source_type, placement.source_id)
            existing = list((await db.execute(select(RuntimeContextOverride).where(
                RuntimeContextOverride.consumer_profile == draft.context.consumer_profile,
                RuntimeContextOverride.project_id == draft.context.project_id,
                RuntimeContextOverride.source_type == placement.source_type,
                RuntimeContextOverride.source_id == placement.source_id,
            ))).scalars())
            for old in existing:
                await db.delete(old)
            if placement.mode != "inherit":
                db.add(RuntimeContextOverride(consumer_profile=draft.context.consumer_profile,
                       project_id=draft.context.project_id, source_type=placement.source_type,
                       source_id=placement.source_id, mode=placement.mode, enabled=True, position=50))
        await db.flush()
    result = await inventory(db, draft.context)
    if result["delivery"]["status"] != "ok":
        raise HTTPException(422, "Canonical assembly failed; changes were not saved")
    from app.services.context_review import deterministic_findings
    result["checks"] = deterministic_findings([s for s in result["sources"] if s["state"] in {"included", "indexed"}])
    result["changes"] = changes
    if not preview:
        result["change_id"] = await record(db, "change", actor, {
            "reason": draft.reason, "changes": changes, "context": draft.context.model_dump(mode="json"),
            "before_placements": before_placements if original_placements is None else original_placements, "after_placements": result["placements"],
        })
    return result


async def preview_draft(db: AsyncSession, draft: ContextDraft) -> dict[str, Any]:
    baseline = await inventory(db, draft.context)
    transaction = await db.begin_nested()
    try:
        result = await apply_draft(db, draft, "preview", preview=True)
        result["baseline"] = baseline["delivery"]
        result["token_delta"] = result["delivery"]["estimated_tokens"] - baseline["delivery"]["estimated_tokens"]
        return result
    finally:
        await transaction.rollback()
        db.expire_all()


async def history(db: AsyncSession, source_id: str | None = None) -> list[dict[str, Any]]:
    statement = select(ContextRecord).order_by(ContextRecord.created_at.desc())
    if source_id is not None:
        statement = statement.where(ContextRecord.source_keys.contains([source_id]))
    records = (await db.execute(statement)).scalars()
    return [{"id": r.id, "kind": r.kind, "actor": r.actor, "created_at": r.created_at.isoformat(), "payload": r.payload}
            for r in records]


async def undo_change(db: AsyncSession, change_id: str, actor: str) -> dict[str, Any]:
    original = await db.get(ContextRecord, change_id)
    if original is None or original.kind != "change":
        raise HTTPException(404, "Change not found")
    payload = original.payload
    context = CanonicalContextDeliveryRequest.model_validate(payload["context"])
    await lock_placement_layer(db, context.consumer_profile, context.project_id)
    current = await placement_snapshot(db, context)
    if current != payload["after_placements"]:
        raise HTTPException(409, "Placement rules changed since this edit; review before undo")
    edits = [SourceEdit(source_type=c["before"]["source_type"], source_id=c["before"]["source_id"],
             expected_revision=c["after_revision"], **{k: c["before"][k] for k in ("name", "content", "summary", "enabled", "policy", "memory_tier", "memory_status", "compact_content") if k in c["before"]})
             for c in payload["changes"]]
    # Restore exact placement snapshots, including order and format, within this transaction.
    rows = list((await db.execute(select(RuntimeContextOverride).where(
        RuntimeContextOverride.consumer_profile == context.consumer_profile,
        RuntimeContextOverride.project_id == context.project_id))).scalars())
    for row in rows:
        await db.delete(row)
    for snapshot in payload["before_placements"]:
        db.add(RuntimeContextOverride(**snapshot, consumer_profile=context.consumer_profile, project_id=context.project_id))
    await db.flush()
    return await apply_draft(db, ContextDraft(context=context, edits=edits, reason=f"Undo {change_id}"), actor, preview=False, original_placements=current)


async def session_workflows(db: AsyncSession, surface: str, session_id: str) -> list[str]:
    row = (await db.execute(select(ContextRecord).where(
        ContextRecord.kind == "workflow",
        ContextRecord.payload["consumer_surface"].as_string() == surface,
        ContextRecord.payload["session_id"].as_string() == session_id,
    ).order_by(ContextRecord.created_at.desc()).limit(1))).scalar_one_or_none()
    return row.payload["workflow_ids"] if row else []


class ContextFeedback(BaseModel):
    source_type: Literal["prompt", "memory"]
    source_id: str
    source_revision: str
    session_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    assessment: Literal["useful", "unnecessary", "conflicting", "incorrect", "missing", "unknown"]
    actor_type: Literal["user", "agent"]
    evidence: str = Field(min_length=1)
    delivery_id: str | None = None


async def record_feedback(db: AsyncSession, request: ContextFeedback, actor: str) -> dict[str, Any]:
    row = await get_source(db, request.source_type, request.source_id)
    payload = request.model_dump()
    payload["matches_current_revision"] = source_revision(row) == request.source_revision
    payload["signal"] = f"{request.actor_type}-rated"
    payload["delivery_verified"] = False
    key = await record(db, "feedback", actor, payload)
    await db.commit()
    return {"id": key, "state": "recorded", "signal": payload["signal"]}
