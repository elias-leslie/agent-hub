"""Selection and execution flow for memory review batches."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_unified import Memory, MemoryReviewRun

from ._review_agent_decisions import MemoryReviewBatchResult
from ._review_agent_prompt import REVIEW_SCHEMA
from ._review_agent_select import select_memories_due_for_review

logger = logging.getLogger(__name__)

DEFAULT_REVIEWER_AGENT = "memory-curator"
DEFAULT_BATCH_LIMIT = 10
DEFAULT_REVIEW_CADENCE_DAYS = 45
MEMORY_REVIEW_LOCK_KEY = "agent-hub:memory-review-worker"


@dataclass(frozen=True)
class _ReviewInputs:
    prompt: str
    sources: list[dict[str, Any]]
    evidence: dict[str, Any]
    reviewer_identity: str
    attempt_key: str


def _failed_result(
    run: MemoryReviewRun,
    *,
    reviewer_agent_slug: str,
    reviewer_model_id: str | None,
    session_id: str | None = None,
    failed_count: int,
    error: str,
) -> MemoryReviewBatchResult:
    return MemoryReviewBatchResult(
        run_id=str(run.id),
        status="failed",
        reviewed_count=0,
        needs_action_count=0,
        failed_count=failed_count,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=reviewer_model_id,
        session_id=session_id,
        errors=[error],
    )


async def _idle_result(
    db: AsyncSession,
    run: MemoryReviewRun,
    reviewer_agent_slug: str,
) -> MemoryReviewBatchResult:
    run.status = "idle"
    run.completed_at = datetime.now(UTC)
    await db.flush()
    return MemoryReviewBatchResult(
        run_id=str(run.id),
        status="idle",
        reviewed_count=0,
        needs_action_count=0,
        failed_count=0,
        reviewer_agent_slug=reviewer_agent_slug,
    )


async def _mark_failed_run(
    db: AsyncSession,
    run: MemoryReviewRun,
    *,
    failed_count: int,
    error: str,
    raw_content: str | None = None,
    reviewer_model_id: str | None = None,
    session_id: str | None = None,
) -> None:
    run.status = "failed"
    run.failed_count = failed_count
    run.reviewer_model_id = reviewer_model_id
    run.completed_at = datetime.now(UTC)
    metadata: dict[str, Any] = dict(run.metadata_ or {})
    metadata["error"] = error
    if session_id is not None:
        metadata["session_id"] = session_id
    if raw_content is not None:
        metadata["raw_content"] = raw_content[:2000]
    attempt = dict(metadata.get("attempt") or {})
    if attempt:
        attempt.update(
            {
                "status": "failed",
                "failure": error,
                "reviewer_model_id": reviewer_model_id,
                "session_id": session_id,
            }
        )
        metadata["attempt"] = attempt
    run.metadata_ = metadata
    await db.flush()


def _memory_review_sources(memories: list[Memory]) -> list[dict[str, Any]]:
    from app.services.context_policy import source_revision, source_snapshot

    return [
        {
            **source_snapshot(memory),
            "revision": source_revision(memory),
            "source_version": memory.version,
        }
        for memory in memories
    ]


async def _reviewer_identity(
    db: AsyncSession,
    *,
    reviewer_agent_slug: str,
    reviewer_model_id: str | None,
    prompt: str,
    schema: dict[str, Any],
) -> str:
    """Fingerprint the actual configured reviewer inputs without credentials."""
    from app.services.context_reviewer_identity import reviewer_identity

    return await reviewer_identity(
        db,
        schema=schema,
        instruction=prompt,
        agent_slug=reviewer_agent_slug,
        model_id=reviewer_model_id,
    )


def _review_attempt_key(
    *,
    reviewer_identity: str,
    evidence: dict[str, Any],
) -> str:
    from app.services.context_policy import semantic_hash

    stable_evidence = dict(evidence)
    if "coverage" in stable_evidence:
        stable_evidence["coverage"] = {key: value for key, value in stable_evidence["coverage"].items()
            if key != "omitted_sources"}
    return semantic_hash(
        {
            "review_workflow": "memory_batch",
            "reviewer_identity": reviewer_identity,
            "evidence": stable_evidence,
        }
    )


async def _find_matching_attempt(
    db: AsyncSession,
    attempt_key: str,
) -> MemoryReviewRun | None:
    """Find a prior reservation without loading unrelated run history."""
    result = await db.execute(
        select(MemoryReviewRun)
        .where(MemoryReviewRun.metadata_.contains({"attempt": {"key": attempt_key}}))
        .order_by(MemoryReviewRun.started_at.desc())
    )
    for candidate in result.scalars().all():
        if candidate.status == "completed":
            return None
        attempt = (candidate.metadata_ or {}).get("attempt") or {}
        if attempt.get("status") in {"reserved", "in_progress", "failed"}:
            return candidate
        if candidate.status == "failed":
            return candidate
    return None


def _blocked_result(
    *,
    run: MemoryReviewRun | None,
    reviewer_agent_slug: str,
    reviewer_model_id: str | None,
    reason: str,
) -> MemoryReviewBatchResult:
    return MemoryReviewBatchResult(
        run_id=str(run.id) if run is not None else None,
        status="blocked",
        reviewed_count=0,
        needs_action_count=0,
        failed_count=0,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=reviewer_model_id,
        errors=[reason],
    )


async def _persist_blocked_attempt(
    db: AsyncSession,
    run: MemoryReviewRun,
    *,
    reason: str,
) -> None:
    metadata = dict(run.metadata_ or {})
    blocked = {
        "status": "blocked",
        "reason": reason,
        "original_run_id": str(run.id),
        "blocked_at": datetime.now(UTC).isoformat(),
    }
    metadata["blocked"] = blocked
    run.metadata_ = metadata
    await db.flush()


async def _apply_review_decisions(
    db: AsyncSession,
    memories: list[Memory],
    decisions: list[Any],
    *,
    dry_run: bool,
) -> int:
    needs_action_count = sum(1 for decision in decisions if decision.review_status == "needs_action")
    if not dry_run:
        from dataclasses import asdict

        from app.services.context_governance import record
        from app.services.context_policy import source_revision, source_snapshot

        by_uuid = {decision.uuid: decision for decision in decisions}
        for memory in memories:
            await record(db, "curator_proposal", "agent:memory-curator", {
                "source": source_snapshot(memory), "revision": source_revision(memory),
                "source_version": memory.version,
                "decision": asdict(by_uuid[str(memory.id)]),
                "coverage": "co-applicable lexical candidates plus required prompt authority; not exhaustive; hidden native prompts unobservable",
                "status": "proposed", "automatic_application": False,
            })
    return needs_action_count


async def _completed_result(
    db: AsyncSession,
    run: MemoryReviewRun,
    *,
    decisions: list[Any],
    needs_action_count: int,
    reviewer_agent_slug: str,
    reviewer_model_id: str | None,
    session_id: str | None,
    dry_run: bool,
    force_all: bool,
    only_missing_compact: bool,
    only_incomplete_audit: bool,
) -> MemoryReviewBatchResult:
    run.status = "completed"
    run.reviewed_count = len(decisions)
    run.needs_action_count = needs_action_count
    run.failed_count = 0
    run.reviewer_model_id = reviewer_model_id
    run.completed_at = datetime.now(UTC)
    metadata = dict(run.metadata_ or {})
    attempt = dict(metadata.get("attempt") or {})
    if attempt:
        attempt.update(
            {
                "status": "completed",
                "reviewer_model_id": reviewer_model_id,
                "session_id": session_id,
                "reviewed_uuids": [decision.uuid for decision in decisions],
            }
        )
        metadata["attempt"] = attempt
    metadata.update({
        "session_id": session_id,
        "dry_run": dry_run,
        "proposal_only": True,
        "force_all": force_all,
        "only_missing_compact": only_missing_compact,
        "only_incomplete_audit": only_incomplete_audit,
        "reviewed_uuids": [decision.uuid for decision in decisions],
    })
    run.metadata_ = metadata
    await db.flush()
    return MemoryReviewBatchResult(
        run_id=str(run.id),
        status="completed",
        reviewed_count=len(decisions),
        needs_action_count=needs_action_count,
        failed_count=0,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=reviewer_model_id,
        session_id=session_id,
    )


async def _record_context_review(
    db: AsyncSession,
    *,
    run: MemoryReviewRun,
    sources: list[dict[str, Any]],
    reviewer_agent_slug: str,
    reviewer_model_id: str | None,
    reviewer_identity: str,
    session_id: str | None,
    failure: str | None = None,
    failure_type: str | None = None,
    raw_content: str | None = None,
) -> str | None:
    """Persist the canonical receipt that drives maintenance ingestion."""
    from app.services.context_governance import record

    payload: dict[str, Any] = {
        "review_workflow": "memory_batch",
        "run_id": str(run.id),
        "attempt_key": (run.metadata_ or {}).get("attempt", {}).get("key"),
        "sources": sources,
        "reviewer_identity": reviewer_identity,
        "reviewer": {
            "agent_slug": reviewer_agent_slug,
            "model": reviewer_model_id,
            "session_id": session_id,
        },
        "coverage": {
            "context": {},
            "workflow": "memory_batch",
            "exact_batch_sources": True,
        },
    }
    if failure is not None:
        payload.update(
            {
                "failure": failure,
                "failure_type": failure_type,
                "failure_evidence": {
                    "run_id": str(run.id),
                    "session_id": session_id,
                    "reviewer_model_id": reviewer_model_id,
                    "raw_content": raw_content,
                },
            }
        )
    receipt_id = await record(db, "context_review", f"agent:{reviewer_agent_slug}", payload)
    run.metadata_ = {**(run.metadata_ or {}), "review_receipt_id": receipt_id}
    return receipt_id


async def _lock_review_sources(
    db: AsyncSession,
    expected_sources: list[dict[str, Any]],
) -> None:
    """Lock and verify the exact source revisions after provider inference."""
    source_ids = [source["source_id"] for source in expected_sources]
    rows = list(
        (
            await db.execute(
                select(Memory)
                .where(Memory.id.in_(source_ids))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    current = {source["source_id"]: source for source in _memory_review_sources(rows)}
    expected = {source["source_id"]: source for source in expected_sources}
    if {
        source_id: (
            current.get(source_id, {}).get("revision"),
            current.get(source_id, {}).get("source_version"),
        )
        for source_id in expected
    } != {
        source_id: (source.get("revision"), source.get("source_version"))
        for source_id, source in expected.items()
    }:
        raise RuntimeError("memory_review_sources_changed")


async def _load_batch_memories(
    db: AsyncSession,
    *,
    batch_limit: int,
    cadence_days: int,
    force_all: bool,
    include_archived: bool,
    only_missing_compact: bool,
    only_incomplete_audit: bool,
) -> list[Memory]:
    return await select_memories_due_for_review(
        db,
        limit=batch_limit,
        cadence_days=cadence_days,
        force_all=force_all,
        include_archived=include_archived,
        only_missing_compact=only_missing_compact,
        only_incomplete_audit=only_incomplete_audit,
    )


async def _prepare_review_inputs(
    db: AsyncSession,
    *,
    facade: Any,
    memories: list[Memory],
    reviewer_agent_slug: str,
    reviewer_model_id: str | None,
) -> _ReviewInputs:
    from sqlalchemy import select

    from app.models.prompt import Prompt
    from app.models.runtime_context import RuntimeContextOverride
    from app.services.context_policy import (
        policies_overlap,
        source_policy,
        source_revision,
        source_snapshot,
    )
    from app.services.context_review import review_candidates
    from app.services.memory.tool_capability_context import (
        format_tool_capability_context,
    )

    governance_snapshot = await facade.collect_memory_governance_snapshot(db)
    memory_index = list(
        (
            await db.execute(
                select(Memory).where(Memory.status == "active").order_by(Memory.scope, Memory.id)
            )
        )
        .scalars()
        .all()
    )
    authority_prompts = list(
        (
            await db.execute(
                select(Prompt).where(Prompt.enabled.is_(True), Prompt.owner_agent_id.is_(None))
            )
        )
        .scalars()
        .all()
    )
    # Curate selected/changed records against co-applicable candidates, not
    # every agent's unrelated system prompt. Required authority stays complete.
    selected = {str(memory.id) for memory in memories}
    corpus = [*memory_index, *authority_prompts]
    snapshots = [source_snapshot(row) for row in corpus]
    candidate_ids = {s["source_id"] for a, b in review_candidates(snapshots)
                     if a["source_id"] in selected or b["source_id"] in selected for s in (a, b)}
    selected_policies = [source_policy(memory) for memory in memories]

    def coapplicable(row: Any) -> bool:
        return any(policies_overlap(source_policy(row), policy) for policy in selected_policies)

    memory_index = [row for row in memory_index if str(row.id) in selected or (str(row.id) in candidate_ids and coapplicable(row))]
    authority_prompts = [row for row in authority_prompts if coapplicable(row) and (source_policy(row).required or row.slug in candidate_ids)]
    authority_ids = {row.slug for row in authority_prompts}
    authority_prompt_assignments = [
        {
            "prompt_slug": row.source_id,
            "consumer_profile": row.consumer_profile,
            "project_id": row.project_id,
            "mode": row.mode,
            "enabled": row.enabled,
        }
        for row in (
            (
                await db.execute(
                    select(RuntimeContextOverride).where(
                        RuntimeContextOverride.source_type == "prompt"
                    )
                )
            )
            .scalars()
            .all()
        )
        if getattr(row, "source_id", None) in authority_ids
    ]
    computed_tool_capabilities = await asyncio.to_thread(
        format_tool_capability_context,
        consumer_profile="agent_startup",
        bash_available=True,
    )
    coverage = {
        "candidate_method": "co-applicable lexical candidates plus required authority",
        "exhaustive": False,
        "omitted_sources": len(corpus) - len(memory_index) - len(authority_prompts),
        "native_prompts": "unobservable; do not infer hidden provider instructions",
    }
    prompt = facade.build_memory_review_prompt(
        memories,
        governance_snapshot=governance_snapshot,
        memory_index=memory_index,
        authority_prompts=authority_prompts,
        authority_prompt_assignments=authority_prompt_assignments,
        computed_tool_capabilities=computed_tool_capabilities,
        coverage=coverage,
    )

    sources = _memory_review_sources(memories)
    evidence = {
        "prompt_builder": await asyncio.to_thread(inspect.getsource, facade.build_memory_review_prompt),
        "schema": REVIEW_SCHEMA,
        "selected_sources": sources,
        "candidate_sources": [
            {**source_snapshot(row), "revision": source_revision(row)}
            for row in [*memory_index, *authority_prompts]
        ],
        "authority_prompt_assignments": authority_prompt_assignments,
        "computed_tool_capabilities": computed_tool_capabilities,
        "coverage": coverage,
    }
    from app.models.context_governance import ContextMaintenanceItem
    repaired = list((await db.execute(select(ContextMaintenanceItem).where(
        ContextMaintenanceItem.kind == "review_failed",
        ContextMaintenanceItem.detail["technical_work"]["receipt"]["status"].as_string() == "completed",
    ).order_by(ContextMaintenanceItem.id))).scalars())
    # Retain successful repair receipts in the identity after queue resolution;
    # otherwise the next cadence would revert to the old failed attempt key.
    selected_revisions = {(s["source_type"], s["source_id"], s["revision"]) for s in sources}
    evidence["technical_revalidation"] = [item.detail["technical_work"]["receipt"] for item in repaired
        if {(s["source_type"], s["source_id"], s["revision"]) for s in item.sources} == selected_revisions]
    identity_instruction = evidence["prompt_builder"]
    identity = await _reviewer_identity(
        db,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=reviewer_model_id,
        prompt=identity_instruction,
        schema=REVIEW_SCHEMA,
    )
    return _ReviewInputs(
        prompt=prompt,
        sources=sources,
        evidence=evidence,
        reviewer_identity=identity,
        attempt_key=_review_attempt_key(reviewer_identity=identity, evidence=evidence),
    )


async def _call_review_for_memories(
    db: AsyncSession,
    *,
    facade: Any,
    memories: list[Memory],
    reviewer_agent_slug: str,
    reviewer_model_id: str | None,
    prepared: _ReviewInputs | None = None,
) -> tuple[str, str | None, str | None]:
    inputs = prepared or await _prepare_review_inputs(
        db,
        facade=facade,
        memories=memories,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=reviewer_model_id,
    )
    return await facade._call_reviewer_agent(
        db,
        reviewer_agent_slug=reviewer_agent_slug,
        prompt=inputs.prompt,
        reviewer_model_id=reviewer_model_id,
        expected_uuids={str(memory.id) for memory in memories},
    )


async def _run_memory_review_batch(
    *,
    db: AsyncSession,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    cadence_days: int = DEFAULT_REVIEW_CADENCE_DAYS,
    reviewer_agent_slug: str = DEFAULT_REVIEWER_AGENT,
    reviewer_model_id: str | None = None,
    dry_run: bool = False,
    force_all: bool = False,
    include_archived: bool = False,
    only_missing_compact: bool = False,
    only_incomplete_audit: bool = False,
) -> MemoryReviewBatchResult:
    """Run one review-agent batch while the caller owns the worker lock."""
    from app.services.memory import review_agent as facade

    memories = await _load_batch_memories(
        db,
        batch_limit=batch_limit,
        cadence_days=cadence_days,
        force_all=force_all,
        include_archived=include_archived,
        only_missing_compact=only_missing_compact,
        only_incomplete_audit=only_incomplete_audit,
    )
    if not memories:
        run = MemoryReviewRun(
            reviewer_agent_slug=reviewer_agent_slug,
            batch_limit=batch_limit,
            dry_run=dry_run,
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.flush()
        return await _idle_result(db, run, reviewer_agent_slug)

    prepared = await _prepare_review_inputs(
        db,
        facade=facade,
        memories=memories,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=reviewer_model_id,
    )
    previous = await _find_matching_attempt(db, prepared.attempt_key)
    if previous is not None:
        prior_attempt = (previous.metadata_ or {}).get("attempt", {})
        prior_status = prior_attempt.get("status") or previous.status
        reason = (
            "Memory review blocked: unchanged attempt is already in progress; "
            f"inspect original run {previous.id} before retrying."
            if prior_status in {"reserved", "in_progress", "running"}
            else
            "Memory review blocked: unchanged attempt already failed; "
            f"inspect original run {previous.id} before retrying."
        )
        await _persist_blocked_attempt(db, previous, reason=reason)
        await _own_blocked_attempt(db, previous, prepared, reviewer_agent_slug, reviewer_model_id, dry_run=dry_run)
        await db.commit()
        return _blocked_result(
            run=previous,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=reviewer_model_id,
            reason=reason,
        )

    run = MemoryReviewRun(
        reviewer_agent_slug=reviewer_agent_slug,
        batch_limit=batch_limit,
        dry_run=dry_run,
        started_at=datetime.now(UTC),
        metadata_={
            "attempt": {
                "key": prepared.attempt_key,
                "status": "reserved",
                "review_workflow": "memory_batch",
                "reviewer_identity": prepared.reviewer_identity,
                "reviewer_agent_slug": reviewer_agent_slug,
                "reviewer_model_id": reviewer_model_id,
                "sources": prepared.sources,
                "reserved_at": datetime.now(UTC).isoformat(),
            }
        },
    )
    db.add(run)
    await db.flush()
    # The reservation must survive a worker restart before any paid provider
    # operation begins. The isolated advisory-lock session remains held while
    # the inference call runs.
    await db.commit()

    expected_uuids = {str(memory.id) for memory in memories}

    raw_content: str | None = None
    session_id: str | None = None
    try:
        raw_content, reviewer_model_id, session_id = await _call_review_for_memories(
            db,
            facade=facade,
            memories=memories,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=reviewer_model_id,
            prepared=prepared,
        )
        await _lock_review_sources(db, prepared.sources)
    except Exception as exc:
        logger.warning("Memory review agent unavailable", exc_info=True)
        if not dry_run:
            await _record_context_review(
                db,
                run=run,
                sources=prepared.sources,
                reviewer_agent_slug=reviewer_agent_slug,
                reviewer_model_id=reviewer_model_id,
                reviewer_identity=prepared.reviewer_identity,
                session_id=session_id,
                failure=str(exc),
                failure_type=type(exc).__name__,
                raw_content=raw_content,
            )
        await _mark_failed_run(
            db,
            run,
            failed_count=len(memories),
            error=str(exc),
            reviewer_model_id=reviewer_model_id,
        )
        return _failed_result(
            run,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=reviewer_model_id,
            failed_count=len(memories),
            error=str(exc),
        )

    assert raw_content is not None
    decisions = facade.parse_memory_review_content(raw_content, expected_uuids)
    if (
        decisions is None
        or len(decisions) != len(memories)
        or not facade.review_decisions_have_complete_checks(decisions)
    ):
        if not dry_run:
            await _record_context_review(
                db,
                run=run,
                sources=prepared.sources,
                reviewer_agent_slug=reviewer_agent_slug,
                reviewer_model_id=reviewer_model_id,
                reviewer_identity=prepared.reviewer_identity,
                session_id=session_id,
                failure="unparseable_review_response",
                failure_type="ReviewResponseParseError",
                raw_content=raw_content,
            )
        await _mark_failed_run(
            db,
            run,
            failed_count=len(memories),
            error="unparseable_review_response",
            raw_content=raw_content,
            reviewer_model_id=reviewer_model_id,
            session_id=session_id,
        )
        return _failed_result(
            run,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=reviewer_model_id,
            session_id=session_id,
            failed_count=len(memories),
            error="unparseable_review_response",
        )

    if not dry_run:
        await _record_context_review(
            db,
            run=run,
            sources=prepared.sources,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=reviewer_model_id,
            reviewer_identity=prepared.reviewer_identity,
            session_id=session_id,
        )

    needs_action_count = await _apply_review_decisions(
        db,
        memories,
        decisions,
        dry_run=dry_run,
    )
    return await _completed_result(
        db,
        run,
        decisions=decisions,
        needs_action_count=needs_action_count,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=reviewer_model_id,
        session_id=session_id,
        dry_run=dry_run,
        force_all=force_all,
        only_missing_compact=only_missing_compact,
        only_incomplete_audit=only_incomplete_audit,
    )


async def _own_blocked_attempt(db: AsyncSession, run: MemoryReviewRun, prepared: _ReviewInputs,
                              agent_slug: str, model_id: str | None, *, dry_run: bool) -> None:
    """An unchanged failure belongs to a technical task, never another blind call."""
    if dry_run:
        return
    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_maintenance import ACTIVE_STATES
    from app.services.context_maintenance_tasks import dispatch_technical_work

    receipt_id = (run.metadata_ or {}).get("review_receipt_id")
    if not receipt_id:
        receipt_id = await _record_context_review(db, run=run, sources=prepared.sources,
            reviewer_agent_slug=agent_slug, reviewer_model_id=model_id, reviewer_identity=prepared.reviewer_identity,
            session_id=(run.metadata_ or {}).get("session_id"), failure="The previous review attempt did not complete; inspect its retained provider evidence before retrying.")
    rows = list((await db.execute(select(ContextMaintenanceItem).where(
        ContextMaintenanceItem.state.in_(ACTIVE_STATES), ContextMaintenanceItem.claim_owner.is_(None),
        ContextMaintenanceItem.evidence_ids.contains([receipt_id])))).scalars())
    for item in rows:
        if item.detail.get("technical_work", {}).get("status") == "completed_pending_revalidation":
            from app.services.context_maintenance_recovery import _failed_revalidation
            await _failed_revalidation(db, item)
        else:
            await dispatch_technical_work(db, item, reason="The regular memory review is blocked on an unchanged failed or interrupted attempt. Diagnose the retained receipt, repair the cause, and verify canonical recovery.")


async def run_memory_review_batch(
    *,
    db: AsyncSession,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    cadence_days: int = DEFAULT_REVIEW_CADENCE_DAYS,
    reviewer_agent_slug: str = DEFAULT_REVIEWER_AGENT,
    reviewer_model_id: str | None = None,
    dry_run: bool = False,
    force_all: bool = False,
    include_archived: bool = False,
    only_missing_compact: bool = False,
    only_incomplete_audit: bool = False,
) -> MemoryReviewBatchResult:
    """Run one review-agent batch under an isolated non-blocking DB lock."""
    from app.db import async_session

    async with async_session() as ownership:
        acquired = (
            await ownership.execute(
                select(
                    func.pg_try_advisory_xact_lock(
                        func.hashtextextended(MEMORY_REVIEW_LOCK_KEY, 0)
                    )
                )
            )
        ).scalar_one()
        if not acquired:
            return _blocked_result(
                run=None,
                reviewer_agent_slug=reviewer_agent_slug,
                reviewer_model_id=reviewer_model_id,
                reason="Memory review blocked: another batch is already in progress.",
            )
        return await _run_memory_review_batch(
            db=db,
            batch_limit=batch_limit,
            cadence_days=cadence_days,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=reviewer_model_id,
            dry_run=dry_run,
            force_all=force_all,
            include_archived=include_archived,
            only_missing_compact=only_missing_compact,
            only_incomplete_audit=only_incomplete_audit,
        )
__all__ = [
    "DEFAULT_BATCH_LIMIT",
    "DEFAULT_REVIEWER_AGENT",
    "DEFAULT_REVIEW_CADENCE_DAYS",
    "run_memory_review_batch",
    "select_memories_due_for_review",
]
