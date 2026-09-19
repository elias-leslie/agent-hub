"""Canonical maintenance work and attention, independent of delivery transport.

Reading and previewing never consume attention. A claim coordinates work; a
finding grants no authority to change instructions or contact the owner.
"""
from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context_governance import (
    ContextMaintenanceAttention,
    ContextMaintenanceIngest,
    ContextMaintenanceItem,
    ContextRecord,
)
from app.services.context_policy import ContextPolicy, policy_match, semantic_hash

ACTIVE_STATES = ("pending", "claimed", "waiting_owner", "deferred")
REVIEW_KINDS = ("context_review", "context_screen", "curator_proposal", "change", "feedback")
CONTEXT_KEYS = ("project_id", "consumer_surface", "consumer_profile", "agent_slug", "workflow_ids", "task_type", "phase", "consumer_tags")


def context_binding(context: dict[str, Any]) -> dict[str, Any]:
    return {key: sorted(set(value)) if isinstance(value, list) else value
            for key in CONTEXT_KEYS if (value := context.get(key))}


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


async def enqueue(db: AsyncSession, *, kind: str, sources: list[dict[str, Any]], context: dict[str, Any],
                  summary: str, recommendation: str, evidence_id: str | None = None,
                  detail: dict[str, Any] | None = None) -> str:
    binding = context_binding(context)
    fingerprint = semantic_hash({"kind": kind, "sources": evidence_identity(sources), "context": binding,
                                 "placement": (detail or {}).get("placement")})
    key = str(uuid.uuid4())
    inserted = (await db.execute(insert(ContextMaintenanceItem).values(
        id=key, fingerprint=fingerprint, kind=kind, state="pending", version=1, summary=summary,
        recommendation=recommendation, sources=sources, context=binding,
        source_keys=sorted({s["source_id"] for s in sources}), evidence_ids=[evidence_id] if evidence_id else [],
        detail=detail or {}, decision={}, resolution={},
    ).on_conflict_do_nothing(index_elements=[ContextMaintenanceItem.fingerprint]).returning(ContextMaintenanceItem.id))).scalar_one_or_none()
    if inserted is not None:
        return inserted
    row = (await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.fingerprint == fingerprint).with_for_update())).scalar_one()
    if kind == "review_failed" and row.state in {"resolved", "dismissed"} and evidence_id and evidence_id not in row.evidence_ids:
        # A later failed audit is a new incident even when its source revision
        # is unchanged. Preserve the prior repair without reusing its task.
        previous = {"resolution": row.resolution, "detail": row.detail}
        generation = row.detail.get("generation", 0) + 1
        row.state, row.version, row.resolution = "pending", row.version + 1, {}
        row.claim_owner, row.claim_session, row.decision = None, None, {}
        row.detail = {**(detail or {}), "generation": generation}
        await maintenance_event(db, row, "system:context-maintenance", "review_failure_recurred", previous)
    if kind in {"token_count", "dangling_placement"} and row.state == "resolved":
        previous = row.resolution
        row.state, row.version, row.resolution = "pending", row.version + 1, {}
        await maintenance_event(db, row, "system:context-maintenance", "derived_drift_recurred", {"previous_resolution": previous})
    if evidence_id and evidence_id not in row.evidence_ids:
        # Repeated evidence neither reopens work nor resets a claim.
        row.evidence_ids = [*row.evidence_ids, evidence_id]
        if (detail or {}).get("handoff_needed") and row.state in ACTIVE_STATES:
            row.detail = {**row.detail, **(detail or {})}
            row.version += 1
    return row.id


async def ingest_review(db: AsyncSession, record: ContextRecord) -> None:
    if record.kind not in REVIEW_KINDS:
        return
    reserved = (await db.execute(insert(ContextMaintenanceIngest).values(record_id=record.id)
        .on_conflict_do_nothing().returning(ContextMaintenanceIngest.record_id))).scalar_one_or_none()
    if reserved is None:
        return
    payload = record.payload
    if record.kind == "change":
        for change in payload.get("changes", []):
            if change["after"].get("enabled") and semantic_hash(change["before"]) != semantic_hash(change["after"]):
                await enqueue(db, kind="review_due", sources=[{**change["after"], "revision": change["after_revision"]}], context={},
                    summary=f"Changed context: {change['after']['name'] or change['after']['source_id']}",
                    recommendation="Review this exact changed source against applicable authority and candidates.",
                    evidence_id=record.id, detail={"change_reason": payload["reason"]})
        return
    if record.kind == "feedback":
        if payload.get("matches_current_revision") and payload.get("assessment") in {"unnecessary", "conflicting", "incorrect", "missing"}:
            from app.services.context_governance import get_source
            from app.services.context_policy import source_revision, source_snapshot
            row = await get_source(db, payload["source_type"], payload["source_id"])
            if source_revision(row) == payload["source_revision"]:
                await enqueue(db, kind="feedback", sources=[{**source_snapshot(row), "revision": source_revision(row)}], context={},
                    summary=f"{payload['signal']} feedback: {payload['assessment']}", recommendation="Assess the retained feedback against current source evidence.",
                    evidence_id=record.id, detail={"feedback": payload})
        return
    sources = payload.get("sources", [])
    context = payload.get("coverage", {}).get("context", {}) if isinstance(payload.get("coverage"), dict) else {}
    if record.kind == "curator_proposal":
        sources = [{**payload["source"], "revision": payload["revision"]}]
        decision = payload["decision"]
        if decision.get("review_status") == "needs_action":
            await enqueue(db, kind="memory_review", sources=sources, context={}, evidence_id=record.id,
                summary=decision.get("reason") or "Memory curator recommends review.",
                recommendation=f"Assess the proposed {decision['decision']} against current instructions and evidence.", detail={"decision": decision, "handoff_needed": True})
    if not any(source.get("source_type") in {"prompt", "memory"} for source in sources):
        # Evaluation fixtures and supplied-native-only experiments are retained
        # as research evidence, never operational maintenance for real sessions.
        return
    if payload.get("failure"):
        await enqueue(db, kind="review_failed", sources=sources, context=context, evidence_id=record.id,
            summary="Context review could not validate its result.", recommendation="Inspect retained failure evidence before requesting another review; do not blindly retry provider calls.",
            detail={"failure": payload["failure"], "handoff_needed": True})
        return
    by_id = {s["source_id"]: s for s in sources}
    for finding in payload.get("findings", []):
        cited = [by_id[key] for key in finding["source_ids"] if key in by_id]
        if not cited:
            continue
        await enqueue(db, kind=finding["kind"], sources=cited, context=context, evidence_id=record.id,
            summary=finding["explanation"], recommendation=finding["remedy"],
            detail={"finding": finding, "handoff_needed": bool(payload.get("reviewer"))})
    for entry in payload.get("entries", []):
        result = entry.get("result") or {}
        relationship = result.get("deterministic_relationship") or result.get("answers", {}).get("relationship", {}).get("choice")
        if relationship not in {"conflict", "redundant"}:
            continue
        cited = [by_id[key] for key in entry["pair"] if key in by_id]
        await enqueue(db, kind="screening_candidate", sources=cited, context=context, evidence_id=record.id,
            summary=f"Optional screening suggests {relationship} instructions.", recommendation="Verify the literal sources independently before proposing a change. Screening is not proof.",
            detail={"relationship": relationship, "screening_only": True})
    # A successful exact-source review repairs an earlier review failure/due item,
    # not its substantive findings. New findings keep their own lifecycle.
    reviewed = {(s["source_type"], s["source_id"], s["revision"]) for s in sources}
    if (record.kind == "context_review" and payload.get("reviewer")) or record.kind == "curator_proposal":
        pending = (await db.execute(select(ContextMaintenanceItem).where(
            ContextMaintenanceItem.state.in_(ACTIVE_STATES), ContextMaintenanceItem.kind.in_(["review_failed", "review_due"])).with_for_update())).scalars()
        for item in pending:
            expected = {(s["source_type"], s["source_id"], s["revision"]) for s in item.sources}
            if expected and expected <= reviewed and all(context_binding(context).get(key) == value for key, value in item.context.items()):
                item.state, item.version = "resolved", item.version + 1
                item.resolution = {"verification": "validated_review_of_exact_sources", "review_id": record.id}
                item.claim_owner, item.claim_session = None, None
                await maintenance_event(db, item, "system:context-maintenance", "review_refreshed", item.resolution)


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
