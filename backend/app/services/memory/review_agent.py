"""Dedicated agent review loop for memory quality and assignment."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AuthenticationError, ProviderError, RateLimitError
from app.models.memory_unified import Memory, MemoryReviewRun

from .governance import collect_memory_governance_snapshot
from .repository import TIER_REVERSE

logger = logging.getLogger(__name__)

DEFAULT_REVIEWER_AGENT = "memory-curator"
DEFAULT_BATCH_LIMIT = 10
DEFAULT_REVIEW_CADENCE_DAYS = 45
MAX_REVIEW_CONTENT_CHARS = 520
MAX_REVIEW_GOVERNANCE_CHARS = 2400
MAX_COMPACT_CONTENT_CHARS = 420
MIN_COMPACT_REVIEW_CONTENT_CHARS = 240
_NORMATIVE_PATTERN = re.compile(
    r"\b(must|never|always|required|require|use|only|do not|don't|cannot|avoid)\b",
    re.IGNORECASE,
)


def _effective_reviewed_at_expr() -> Any:
    source_validated_at = cast(
        func.nullif(Memory.metadata_["source_compact_validated_at"].astext, ""),
        DateTime(timezone=True),
    )
    return func.coalesce(Memory.last_reviewed_at, source_validated_at)

_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "uuid": {"type": "string"},
                    "decision": {
                        "type": "string",
                        "enum": ["keep", "retarget", "compress", "archive", "merge", "split"],
                    },
                    "review_status": {
                        "type": "string",
                        "enum": ["clean", "needs_action"],
                    },
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                    "suggested_summary": {"type": ["string", "null"]},
                    "compact_content": {"type": ["string", "null"]},
                    "suggested_tags": {"type": "array", "items": {"type": "string"}},
                    "suggested_applicability": {"type": "object"},
                    "sensitivity_tier": {
                        "type": "string",
                        "enum": ["normal", "personal", "confidential"],
                    },
                },
                "required": [
                    "uuid",
                    "decision",
                    "review_status",
                    "confidence",
                    "reason",
                    "suggested_summary",
                    "suggested_tags",
                    "suggested_applicability",
                    "sensitivity_tier",
                ],
            },
        }
    },
    "required": ["reviews"],
}

_CLEAN_DECISION_ALIASES = {"ok", "okay", "pass", "valid", "clean"}
_ACTION_DECISION_ALIASES = {
    "action",
    "fix",
    "needs-action",
    "needs_action",
    "needs review",
    "needs_review",
    "review",
    "reroute",
    "reassign",
    "target",
}
_ARCHIVE_DECISION_ALIASES = {"delete", "remove", "prune", "retire", "archive_or_delete"}


def _normalize_review_decision(decision: str, review_status: str, has_compact: bool) -> str | None:
    """Normalize reviewer shorthand into persisted decision classes."""
    if decision in {"keep", "retarget", "compress", "archive", "merge", "split"}:
        return decision
    if decision in _CLEAN_DECISION_ALIASES:
        return "keep"
    if decision in _ACTION_DECISION_ALIASES:
        return "retarget"
    if decision in _ARCHIVE_DECISION_ALIASES:
        return "archive"
    compactish = any(token in decision for token in ("compact", "compress", "shorten"))
    targetish = any(token in decision for token in ("target", "route", "scope", "assign"))
    archiveish = any(token in decision for token in ("archive", "delete", "remove", "replace"))
    if archiveish:
        return "archive"
    if compactish and not targetish:
        return "compress"
    if targetish:
        return "retarget"
    if decision.startswith("keep"):
        if review_status == "clean":
            return "keep"
        return "compress" if has_compact else "retarget"
    return None


def _normalize_review_status(review_status: str, decision: str) -> str:
    """Normalize reviewer status shorthand into clean/needs_action."""
    status = review_status.strip().lower()
    if status in {"clean", "needs_action"}:
        return status
    if status in _CLEAN_DECISION_ALIASES:
        return "clean"
    actionish = any(
        token in status
        for token in ("action", "target", "route", "compact", "compress", "archive", "fix")
    )
    if actionish:
        return "needs_action"
    if "clean" in status:
        return "clean"
    if decision == "keep" or decision in _CLEAN_DECISION_ALIASES:
        return "clean"
    return "needs_action"


@dataclass
class MemoryReviewDecision:
    """Parsed review-agent decision for one memory."""

    uuid: str
    decision: str
    review_status: str
    confidence: float
    reason: str
    suggested_summary: str | None = None
    compact_content: str | None = None
    suggested_tags: list[str] = field(default_factory=list)
    suggested_applicability: dict[str, Any] = field(default_factory=dict)
    sensitivity_tier: str = "normal"


@dataclass
class MemoryReviewBatchResult:
    """Result of one review batch."""

    run_id: str | None
    status: str
    reviewed_count: int
    needs_action_count: int
    failed_count: int
    reviewer_agent_slug: str
    reviewer_model_id: str | None = None
    session_id: str | None = None
    errors: list[str] = field(default_factory=list)


def _memory_payload(memory: Memory) -> dict[str, Any]:
    content = " ".join((memory.content or "").split())
    payload: dict[str, Any] = {
        "uuid": str(memory.id),
        "uuid8": memory.uuid_short,
        "name": memory.name,
        "summary": memory.summary,
        "content": content[:MAX_REVIEW_CONTENT_CHARS],
        "content_chars": len(content),
        "memory_type": memory.memory_type,
        "tier": TIER_REVERSE.get(int(memory.tier or 0), "reference"),
        "context_kind": memory.context_kind,
        "scope": memory.scope,
        "scope_id": memory.scope_id,
        "group_id": memory.group_id,
        "tags": list(memory.tags or []),
        "applicability": dict(memory.applicability or {}),
        "trigger_task_types": list(memory.trigger_task_types or []),
        "trigger_phases": list(memory.trigger_phases or []),
        "usage": {
            "loaded": int(memory.loaded_count or 0),
            "referenced": int(memory.referenced_count or 0),
            "helpful": int(memory.helpful_count or 0),
            "harmful": int(memory.harmful_count or 0),
        },
        "token_count": memory.token_count,
        "review_status": memory.review_status,
        "compact_content": (memory.metadata_ or {}).get("compact_content"),
        "compact_status": (memory.metadata_ or {}).get("compact_status"),
        "compact_reviewed_at": (memory.metadata_ or {}).get("compact_reviewed_at"),
        "last_reviewed_at": memory.last_reviewed_at.isoformat()
        if memory.last_reviewed_at
        else None,
    }
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }


def build_memory_review_prompt(
    memories: list[Memory],
    *,
    governance_snapshot: dict[str, Any],
) -> str:
    """Build bounded prompt for the memory-curator agent."""
    payload = [_memory_payload(memory) for memory in memories]
    governance_json = json.dumps(
        governance_snapshot,
        separators=(",", ":"),
        sort_keys=True,
    )[:MAX_REVIEW_GOVERNANCE_CHARS]
    memories_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return (
        "Review these Agent Hub memories for quality, token efficiency, staleness, "
        "assignment, scope, and routing.\n\n"
        "Use compact evidence only. Return review decisions only. "
        "Prefer compact summaries and targeted applicability. Mark needs_action when content is "
        "stale, too broad, too long for its tier, assigned to wrong consumers, "
        "duplicative, or risky.\n\n"
        "For any useful memory over ~60 tokens, provide compact_content: the prompt-ready "
        "version to inject instead of full content. Preserve all hard directives and normative "
        "force (must, never, always, required, only, do not). Compact first; do not rely on "
        "dropping useful memories to save tokens.\n\n"
        "Consumer profiles: codex_startup, claude_session_start, agent_coding, "
        "agent_operator, agent_promptops, agent_general, agent_visual, agent_runtime.\n"
        "Policy memories should not be agent-targeted unless there is a strong reason. "
        "References and capabilities should be targeted when broad injection would bloat context.\n\n"
        f"Governance snapshot:\n{governance_json}\n\n"
        f"Memories:\n{memories_json}\n\n"
        "Return JSON only matching the provided schema."
    )


def parse_memory_review_content(
    content: str | None,
    expected_uuids: set[str],
) -> list[MemoryReviewDecision] | None:
    """Parse review-agent JSON into decisions."""
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        review_items = parsed
    elif isinstance(parsed, dict):
        review_items = parsed.get("reviews")
        if not isinstance(review_items, list):
            review_items = parsed.get("decisions")
    else:
        return None
    if not isinstance(review_items, list):
        return None

    decisions: list[MemoryReviewDecision] = []
    uuid_prefixes: dict[str, str | None] = {}
    for expected_uuid in expected_uuids:
        prefix = expected_uuid[:8]
        uuid_prefixes[prefix] = expected_uuid if prefix not in uuid_prefixes else None
    for item in review_items:
        if not isinstance(item, dict):
            return None
        uuid = str(item.get("uuid") or item.get("uuid8") or "")
        raw_uuid8 = str(item.get("uuid8") or "")
        if uuid not in expected_uuids and len(uuid) == 8:
            uuid = uuid_prefixes.get(uuid) or uuid
        if uuid not in expected_uuids and raw_uuid8:
            uuid = uuid_prefixes.get(raw_uuid8[:8]) or uuid
        if uuid not in expected_uuids:
            return None
        decision = str(item.get("decision") or "").strip().lower()
        review_status = str(item.get("review_status") or "")
        needs_action_flag = item.get("needs_action")
        if not review_status and isinstance(needs_action_flag, bool):
            review_status = "needs_action" if needs_action_flag else "clean"
        if decision in {"clean", "needs_action"} and not review_status:
            review_status = decision
            decision = "keep" if review_status == "clean" else "retarget"
        elif decision in _CLEAN_DECISION_ALIASES:
            review_status = review_status or "clean"
        elif decision in _ACTION_DECISION_ALIASES or decision in _ARCHIVE_DECISION_ALIASES:
            review_status = review_status or "needs_action"
        if not review_status:
            review_status = "clean" if decision == "keep" else "needs_action"
        review_status = _normalize_review_status(review_status, decision)
        reason = str(item.get("reason") or item.get("evidence") or item.get("rationale") or "").strip()
        issues = item.get("issues") or item.get("reasons")
        if not reason and isinstance(issues, list):
            reason = "; ".join(str(issue).strip() for issue in issues if str(issue).strip())
        if not reason and review_status == "clean":
            reason = "No issues reported."
        if review_status not in {"clean", "needs_action"} or not reason:
            return None
        compact_content = _normalize_compact_content(
            original="",
            candidate=(
                item.get("compact_content")
                or item.get("suggested_compact_content")
                or item.get("prompt_content")
                or item.get("compressed_content")
            ),
        )
        if not decision:
            decision = "keep" if review_status == "clean" else "retarget"
        normalized_decision = _normalize_review_decision(
            decision,
            review_status,
            compact_content is not None,
        )
        if normalized_decision is None:
            return None
        decision = normalized_decision
        sensitivity_tier = str(item.get("sensitivity_tier") or "normal")
        if sensitivity_tier not in {"normal", "personal", "confidential"}:
            sensitivity_tier = "normal"
        suggested_summary = item.get("suggested_summary")
        if isinstance(item.get("suggested_applicability"), dict):
            suggested_applicability = item["suggested_applicability"]
        elif isinstance(item.get("applicability"), dict):
            suggested_applicability = item["applicability"]
        elif isinstance(item.get("assignment"), dict):
            suggested_applicability = item["assignment"]
        elif isinstance(item.get("targeting"), dict):
            suggested_applicability = item["targeting"]
        else:
            suggested_applicability = {}
        recommended_scope = item.get("recommended_scope")
        recommended_scope_id = item.get("recommended_scope_id")
        recommended_context_kind = item.get("recommended_context_kind")
        recommended_tier = item.get("recommended_tier")
        recommended_consumer_profiles = item.get("recommended_consumer_profiles")
        if any(
            value is not None
            for value in (
                recommended_scope,
                recommended_scope_id,
                recommended_context_kind,
                recommended_tier,
                recommended_consumer_profiles,
            )
        ):
            suggested_applicability = dict(suggested_applicability)
            if isinstance(recommended_scope, str):
                suggested_applicability.setdefault("scope", recommended_scope)
            if isinstance(recommended_scope_id, str):
                suggested_applicability.setdefault("scope_id", recommended_scope_id)
            if isinstance(recommended_context_kind, str):
                suggested_applicability.setdefault("context_kind", recommended_context_kind)
            if isinstance(recommended_tier, str):
                suggested_applicability.setdefault("tier", recommended_tier)
            if isinstance(recommended_consumer_profiles, list):
                suggested_applicability.setdefault(
                    "consumer_profiles",
                    [value for value in recommended_consumer_profiles if isinstance(value, str)],
                )
        target_consumers = (
            item.get("target_consumers")
            or item.get("target_consumer_profiles")
            or item.get("routing")
        )
        if isinstance(target_consumers, list):
            suggested_applicability = dict(suggested_applicability)
            suggested_applicability.setdefault(
                "consumer_profiles",
                [value for value in target_consumers if isinstance(value, str)],
            )
        decisions.append(
            MemoryReviewDecision(
                uuid=uuid,
                decision=decision,
                review_status=review_status,
                confidence=float(item.get("confidence") or 0.75),
                reason=reason[:500],
                suggested_summary=suggested_summary if isinstance(suggested_summary, str) else None,
                compact_content=compact_content,
                suggested_tags=[
                    tag.strip()
                    for tag in item.get("suggested_tags", [])
                    if isinstance(tag, str) and tag.strip()
                ][:12],
                suggested_applicability=suggested_applicability,
                sensitivity_tier=sensitivity_tier,
            )
        )
    return decisions


def _normalize_compact_content(
    *,
    original: str,
    candidate: Any,
) -> str | None:
    """Validate compact prompt text before persisting it."""
    if not isinstance(candidate, str):
        return None
    compact = " ".join(candidate.split())
    if not compact:
        return None
    if len(compact) > MAX_COMPACT_CONTENT_CHARS:
        compact = compact[:MAX_COMPACT_CONTENT_CHARS].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
    if original:
        full = " ".join(original.split())
        if len(compact) >= len(full):
            return None
        original_markers = {marker.lower() for marker in _NORMATIVE_PATTERN.findall(full)}
        compact_markers = {marker.lower() for marker in _NORMATIVE_PATTERN.findall(compact)}
        if original_markers and not original_markers.intersection(compact_markers):
            return None
    return compact


async def select_memories_due_for_review(
    db: AsyncSession,
    *,
    limit: int = DEFAULT_BATCH_LIMIT,
    cadence_days: int = DEFAULT_REVIEW_CADENCE_DAYS,
    force_all: bool = False,
    include_archived: bool = False,
    only_missing_compact: bool = False,
) -> list[Memory]:
    """Select active memories due for rolling review, oldest first."""
    cutoff = datetime.now(UTC) - timedelta(days=cadence_days)
    statuses = ["active", "archived"] if include_archived else ["active"]
    filters: list[Any] = [Memory.status.in_(statuses)]
    if only_missing_compact:
        filters.extend(
            [
                text("coalesce(memories.metadata->>'compact_content', '') = ''"),
                text("memories.metadata->>'compact_reviewed_at' is null"),
                func.length(Memory.content) > MIN_COMPACT_REVIEW_CONTENT_CHARS,
            ]
        )
    if not force_all:
        effective_reviewed_at = _effective_reviewed_at_expr()
        filters.append(or_(effective_reviewed_at.is_(None), effective_reviewed_at < cutoff))
    effective_reviewed_at = _effective_reviewed_at_expr()
    stmt = (
        select(Memory)
        .where(*filters)
        .order_by(effective_reviewed_at.asc().nulls_first(), Memory.created_at.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _call_reviewer_agent(
    db: AsyncSession,
    *,
    reviewer_agent_slug: str,
    prompt: str,
    reviewer_model_id: str | None = None,
) -> tuple[str, str | None, str | None]:
    from app.api.complete.core import complete_internal
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

    resolved = await resolve_agent(reviewer_agent_slug, db)
    mandate = await inject_agent_mandates(
        resolved.agent,
        db,
        prompt_mode="minimal",
        project_id="agent-hub",
        task_type="review",
    )
    messages: list[dict[str, Any]] = []
    if mandate.system_content:
        messages.append({"role": "system", "content": mandate.system_content})
    messages.append({"role": "user", "content": prompt})
    candidate_models = [
        *( [reviewer_model_id] if reviewer_model_id else [] ),
        resolved.model,
        *list(resolved.agent.fallback_models or []),
    ]
    last_error: Exception | None = None
    for model in dict.fromkeys(candidate_models):
        provider = resolved.provider if model == resolved.model else get_provider_for_model(model)
        try:
            result = await complete_internal(
                messages=messages,
                model=model,
                provider=provider,
                temperature=resolved.agent.temperature,
                project_id="agent-hub",
                db=db,
                agent_slug=reviewer_agent_slug,
                request_source="memory_review",
                use_memory=False,
                enable_caching=False,
                skip_cache=True,
                max_turns=1,
                execute_tools=False,
                thinking_level=resolved.agent.thinking_level,
                response_format={"type": "json_object", "schema": _REVIEW_SCHEMA},
                task_type="review",
                phase="memory_review",
            )
            return result.content, model, result.session_id
        except Exception as exc:
            last_error = exc
            if isinstance(exc, AuthenticationError):
                raise
            if not isinstance(exc, RateLimitError) and not (
                isinstance(exc, ProviderError) and exc.retriable
            ):
                raise
            logger.warning("Memory review model %s failed; trying fallback: %s", model, exc)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"No reviewer models configured for {reviewer_agent_slug}")


def _apply_decision(memory: Memory, decision: MemoryReviewDecision, now: datetime) -> None:
    metadata = dict(memory.metadata_ or {})
    review_history = list(metadata.get("review_history") or [])[-4:]
    compact_content = _normalize_compact_content(
        original=memory.content or "",
        candidate=decision.compact_content,
    )
    review_entry = {
        "reviewed_at": now.isoformat(),
        "decision": decision.decision,
        "review_status": decision.review_status,
        "confidence": round(decision.confidence, 3),
        "reason": decision.reason,
        "suggested_summary": decision.suggested_summary,
        "compact_content": compact_content,
        "suggested_tags": decision.suggested_tags,
        "suggested_applicability": decision.suggested_applicability,
        "sensitivity_tier": decision.sensitivity_tier,
    }
    review_history.append(review_entry)
    metadata["last_review"] = review_entry
    metadata["review_history"] = review_history
    metadata["compact_reviewed_at"] = now.isoformat()
    if decision.review_status == "needs_action":
        metadata["review_queue"] = review_entry
    else:
        metadata.pop("review_queue", None)
    if compact_content:
        metadata["compact_content"] = compact_content
        metadata["compact_status"] = "ready"
    else:
        metadata["compact_status"] = (
            "not_needed"
            if len(" ".join((memory.content or "").split())) <= MIN_COMPACT_REVIEW_CONTENT_CHARS
            else "not_provided"
        )
    memory.metadata_ = metadata
    memory.review_status = decision.review_status
    memory.sensitivity_tier = decision.sensitivity_tier
    memory.last_reviewed_at = now
    memory.updated_at = now


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
) -> MemoryReviewBatchResult:
    """Run one review-agent batch and persist review metadata."""
    now = datetime.now(UTC)
    run = MemoryReviewRun(
        reviewer_agent_slug=reviewer_agent_slug,
        batch_limit=batch_limit,
        dry_run=dry_run,
        started_at=now,
    )
    db.add(run)
    await db.flush()

    memories = await select_memories_due_for_review(
        db,
        limit=batch_limit,
        cadence_days=cadence_days,
        force_all=force_all,
        include_archived=include_archived,
        only_missing_compact=only_missing_compact,
    )
    if not memories:
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

    governance_snapshot = await collect_memory_governance_snapshot(db)
    prompt = build_memory_review_prompt(memories, governance_snapshot=governance_snapshot)
    expected_uuids = {str(memory.id) for memory in memories}

    try:
        raw_content, reviewer_model_id, session_id = await _call_reviewer_agent(
            db,
            reviewer_agent_slug=reviewer_agent_slug,
            prompt=prompt,
            reviewer_model_id=reviewer_model_id,
        )
    except Exception as exc:
        logger.warning("Memory review agent unavailable", exc_info=True)
        run.status = "failed"
        run.failed_count = len(memories)
        run.completed_at = datetime.now(UTC)
        run.metadata_ = {"error": str(exc)}
        await db.flush()
        return MemoryReviewBatchResult(
            run_id=str(run.id),
            status="failed",
            reviewed_count=0,
            needs_action_count=0,
            failed_count=len(memories),
            reviewer_agent_slug=reviewer_agent_slug,
            errors=[str(exc)],
        )

    decisions = parse_memory_review_content(raw_content, expected_uuids)
    if decisions is None or len(decisions) != len(memories):
        run.status = "failed"
        run.failed_count = len(memories)
        run.reviewer_model_id = reviewer_model_id
        run.completed_at = datetime.now(UTC)
        run.metadata_ = {"error": "unparseable_review_response", "raw_content": raw_content[:2000]}
        await db.flush()
        return MemoryReviewBatchResult(
            run_id=str(run.id),
            status="failed",
            reviewed_count=0,
            needs_action_count=0,
            failed_count=len(memories),
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=reviewer_model_id,
            session_id=session_id,
            errors=["unparseable_review_response"],
        )

    by_uuid = {decision.uuid: decision for decision in decisions}
    needs_action_count = sum(1 for decision in decisions if decision.review_status == "needs_action")
    if not dry_run:
        for memory in memories:
            _apply_decision(memory, by_uuid[str(memory.id)], datetime.now(UTC))

    run.status = "completed"
    run.reviewed_count = len(decisions)
    run.needs_action_count = needs_action_count
    run.failed_count = 0
    run.reviewer_model_id = reviewer_model_id
    run.completed_at = datetime.now(UTC)
    run.metadata_ = {
        "session_id": session_id,
        "dry_run": dry_run,
        "force_all": force_all,
        "only_missing_compact": only_missing_compact,
        "reviewed_uuids": [decision.uuid for decision in decisions],
    }
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
