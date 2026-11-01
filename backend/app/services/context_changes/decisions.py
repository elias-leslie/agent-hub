"""Keep, rework or refuse queued context changes, after the fact.

- Keep records the decision through the revision the reviewer saw; nothing else changes.
- Rework edits the target in place or narrows who receives it (global -> project -> role -> session-only, which
  archives it), writing one revision as the reviewer.
- Refuse undoes the unreviewed changes: a create is archived (its revisions stay), an update or delete is restored to
  the revision before the first unreviewed one, through the M0 restore (every field, re-embedded, row lock and
  memories.version check). A placement change puts the layer's earlier rules back.

Rework and refuse need the target's latest revision to be the one the reviewer saw (``through_revision``) and, for a
memory, memories.version to be the version they saw; anything newer raises ``ReviewConflict`` (HTTP 409, reload).
The checks run under the same row lock (or placement-layer lock) as the write. Several items decided together run
in one transaction, locked in a fixed order: one conflict changes nothing. Nothing here commits; the caller does.
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_actor import attribute, current_request_writer
from app.models.context_change_review import ContextChangeReview
from app.models.memory_unified import Memory, MemoryRevision
from app.models.prompt import Prompt, PromptRevision
from app.models.runtime_context import RuntimeContextOverride
from app.services.context_policy import (
    ContextPolicy,
    lock_placement_layer,
    semantic_hash,
    source_policy,
)
from app.services.context_writer import resolve_writers
from app.services.memory._repo_revisions import RevisionConflictError, _embed_or_none
from app.services.memory.applicability import ROLE_CONSUMER_TAGS, WORK_ROLE_TAG_PREFIX
from app.services.memory.repository import MemoryRepository
from app.services.prompt_service import (
    PromptRevisionConflictError,
    _sync_owned_agent_system_prompt_mirror,
    lock_prompt_by_slug,
    record_prompt_revision,
    restore_prompt_revision,
)

from .queue import (
    Fold,
    Step,
    TargetKind,
    WriterView,
    layer_request,
    parse_placement_key,
    session_of,
    target_fold,
)

Decision = Literal["keep", "rework", "refuse"]


class ReviewConflict(Exception):
    """The target changed since the reviewer looked (or was decided meanwhile); reload before acting."""

    def __init__(self, key: str, message: str, *, latest_revision: str | None = None) -> None:
        self.key, self.latest_revision = key, latest_revision
        super().__init__(message)


class ReviewItem(BaseModel):
    target_kind: TargetKind
    target_id: str = Field(min_length=1, max_length=200)
    through_revision: str = Field(min_length=1, max_length=36, description="The latest revision the reviewer saw")
    expected_version: int | None = Field(None, description="memories.version the reviewer saw (memory only)")

    @property
    def key(self) -> str:
        return f"{self.target_kind}:{self.target_id}"


class DecideRequest(BaseModel):
    items: list[ReviewItem] = Field(min_length=1, max_length=200)
    note: str | None = Field(None, max_length=2000)


class Narrow(BaseModel):
    """Who should receive it instead: one project, one work role (in its current or a given project), or only the
    session that wrote it (archived)."""

    to: Literal["project", "role", "session"]
    project_id: str | None = Field(None, max_length=100)
    role: str | None = Field(None, max_length=50)

    @model_validator(mode="after")
    def check(self) -> Narrow:
        if self.to == "role" and (not self.role or WORK_ROLE_TAG_PREFIX + self.role not in ROLE_CONSUMER_TAGS):
            raise ValueError("Narrow to a registered work role")
        return self


class Edit(BaseModel):
    content: str | None = Field(None, min_length=1)
    summary: str | None = None
    name: str | None = Field(None, max_length=200)


class ReworkRequest(ReviewItem):
    edit: Edit | None = None
    narrow: Narrow | None = None
    note: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def check(self) -> ReworkRequest:
        if self.edit is None and self.narrow is None:
            raise ValueError("Rework needs an edit or a narrow")
        if self.target_kind == "placement":
            raise ValueError("Placement changes can be kept or refused")
        return self


class DecisionResult(BaseModel):
    key: str
    decision: Decision
    review_id: str
    through_revision: str
    result_revision: str | None
    outcome: str  # recorded | archived | restored | disabled | edited | narrowed | nothing to undo


class DecideResponse(BaseModel):
    results: list[DecisionResult]
    linked_pending: list[str] = Field(default_factory=list,
                                      description="Unreviewed rows from the same sessions that were not decided")


@dataclass
class Touched:
    """What the caller must refresh after commit (agent caches for agent-owned prompts)."""

    prompts: list[Prompt] = field(default_factory=list)


def _changed_by(decision: Decision) -> str:
    return f"review:{decision}"


async def _record_review(
    db: AsyncSession, item: ReviewItem, decision: Decision, *, through: Step, result: tuple[str, datetime] | None,
    note: str | None, previous_covered: datetime | None,
) -> ContextChangeReview:
    covered = max(t for t in (through.at, result[1] if result else None, previous_covered) if t is not None)
    writer = current_request_writer()
    review = ContextChangeReview(
        id=_uuid.uuid4(), target_kind=item.target_kind, target_id=item.target_id, through_revision=through.id,
        result_revision=None if result is None else result[0], covered_until=covered, decision=decision, note=note,
        by=attribute(None) or writer.kind, by_kind=writer.kind, by_session=writer.session,
    )
    db.add(review)
    await db.flush()
    return review


def _through(item: ReviewItem, target: Fold) -> Step:
    step = next((s for s in target.steps if s.id == item.through_revision), None)
    if step is None:
        raise HTTPException(404, f"{item.key}: revision {item.through_revision[:8]} is not part of its history")
    return step


def _require_latest(item: ReviewItem, target: Fold) -> Step:
    """The reviewer's revision must still be the latest, with unreviewed changes left to act on."""
    through = _through(item, target)
    latest = target.latest
    if latest is None or latest.id != through.id:
        raise ReviewConflict(item.key, f"{item.key} changed since you looked; reload before deciding",
                             latest_revision=None if latest is None else latest.id)
    return through


def _sorted(items: list[ReviewItem]) -> list[ReviewItem]:
    keys = [i.key for i in items]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, "Each change can be decided once per request")
    return sorted(items, key=lambda i: (i.target_kind, i.target_id))  # fixed lock order: no deadlocks


async def keep(db: AsyncSession, request: DecideRequest) -> DecideResponse:
    results = []
    sessions: set[str] = set()
    for item in _sorted(request.items):
        target = await target_fold(db, item.target_kind, item.target_id)
        sessions |= _pending_sessions(target)
        through = _through(item, target)
        review = await _record_review(db, item, "keep", through=through, result=None, note=request.note,
                                      previous_covered=target.covered_until)
        results.append(DecisionResult(key=item.key, decision="keep", review_id=str(review.id),
                                      through_revision=through.id, result_revision=None, outcome="recorded"))
    return DecideResponse(results=results, linked_pending=await _linked_pending(db, request.items, sessions))


async def refuse(db: AsyncSession, request: DecideRequest, touched: Touched | None = None) -> DecideResponse:
    touched = touched or Touched()
    results = []
    sessions: set[str] = set()
    for item in _sorted(request.items):
        target = await target_fold(db, item.target_kind, item.target_id)
        sessions |= _pending_sessions(target)
        through = _require_latest(item, target)
        if not target.pending:
            raise ReviewConflict(item.key, f"{item.key} has no unreviewed change left; reload",
                                 latest_revision=through.id)
        if item.target_kind == "memory":
            outcome, result = await _refuse_memory(db, item, target, through, request.note)
        elif item.target_kind == "prompt":
            outcome, result = await _refuse_prompt(db, item, target, through, request.note, touched)
        else:
            outcome, result = await _refuse_placement(db, item, target, through, request.note)
        review = await _record_review(db, item, "refuse", through=through, result=result, note=request.note,
                                      previous_covered=target.covered_until)
        results.append(DecisionResult(key=item.key, decision="refuse", review_id=str(review.id),
                                      through_revision=through.id, result_revision=None if result is None else result[0],
                                      outcome=outcome))
    return DecideResponse(results=results, linked_pending=await _linked_pending(db, request.items, sessions))


async def rework(db: AsyncSession, request: ReworkRequest, touched: Touched | None = None) -> DecideResponse:
    touched = touched or Touched()
    target = await target_fold(db, request.target_kind, request.target_id)
    through = _require_latest(request, target)
    if request.target_kind == "memory":
        outcome, result = await _rework_memory(db, request, target, through)
    else:
        outcome, result = await _rework_prompt(db, request, through, touched)
    review = await _record_review(db, request, "rework", through=through, result=result, note=request.note,
                                  previous_covered=target.covered_until)
    return DecideResponse(results=[DecisionResult(
        key=request.key, decision="rework", review_id=str(review.id), through_revision=through.id,
        result_revision=result[0], outcome=outcome)],
        linked_pending=await _linked_pending(db, [request], _pending_sessions(target)))


def _pending_sessions(target: Fold) -> set[str]:
    return {name for step in target.pending if (name := session_of(step))}


async def _linked_pending(db: AsyncSession, items: list[ReviewItem], sessions: set[str]) -> list[str]:
    """Rows still unreviewed that were written by the same sessions as the decided changes."""
    from .queue import build_queue

    if not sessions:
        return []
    decided = {i.key for i in items}
    rows = (await build_queue(db)).rows
    return sorted(r.key for r in rows if r.key not in decided and sessions.intersection(r.sessions))


# ---------------------------------------------------------------------------------------------------------------
# Memory


async def _latest_memory_revision(db: AsyncSession, memory_uuid: str) -> MemoryRevision:
    return (await db.execute(
        select(MemoryRevision).where(MemoryRevision.memory_uuid == memory_uuid)
        .order_by(MemoryRevision.created_at.desc(), MemoryRevision.version.desc()).limit(1)
    )).scalar_one()


async def _lock_memory(db: AsyncSession, item: ReviewItem, through: Step) -> Memory | None:
    """The memory row, locked, at the version the reviewer saw; else ReviewConflict."""
    memory = await db.get(Memory, _uuid.UUID(item.target_id), with_for_update=True, populate_existing=True)
    expected = item.expected_version if item.expected_version is not None else through.version
    if memory is not None:
        current = int(memory.version or 1)
    else:
        current = max((int(s.version or 0) for s in (await target_fold(db, "memory", item.target_id)).steps),
                      default=0)
    if expected is not None and current != expected:
        raise ReviewConflict(item.key, f"{item.key} changed (expected version {expected}, now {current}); reload",
                             latest_revision=through.id)
    return memory


async def _refuse_memory(
    db: AsyncSession, item: ReviewItem, target: Fold, through: Step, note: str | None,
) -> tuple[str, tuple[str, datetime] | None]:
    base = target.base
    reason = note or "Refused in context review"
    if base is None or base.action == "delete":
        # A create (or a re-create after a delete): archive it, its revisions stay.
        memory = await _lock_memory(db, item, through)
        if memory is None:
            return "nothing to undo", None
        if memory.status != "archived":
            await MemoryRepository().update(memory.id, db=db, status="archived", action="refuse",
                                            changed_by=_changed_by("refuse"), change_reason=reason)
        revision = await _latest_memory_revision(db, item.target_id)
        return "archived", (str(revision.id), revision.created_at)
    expected = item.expected_version if item.expected_version is not None else through.version
    try:
        restored = await MemoryRepository().restore_revision(
            item.target_id, base.id, expected_version=expected, changed_by=_changed_by("refuse"),
            change_reason=reason, db=db,
        )
    except RevisionConflictError as exc:
        raise ReviewConflict(item.key, str(exc), latest_revision=through.id) from exc
    if restored is None:  # pragma: no cover - base came from this history
        raise HTTPException(404, f"{item.key}: revision {base.id[:8]} is gone")
    revision = await _latest_memory_revision(db, item.target_id)
    return "restored", (restored.revision_id, revision.created_at)


async def _rework_memory(
    db: AsyncSession, request: ReworkRequest, target: Fold, through: Step,
) -> tuple[str, tuple[str, datetime]]:
    updates: dict[str, Any] = {}
    outcome = []
    if request.edit is not None:
        if request.edit.content is not None:
            # Embedded before the row lock (a network call); a failed embed leaves the vector empty, like restore.
            updates["content"] = request.edit.content
            updates["embedding"] = await _embed_or_none(request.target_id, request.edit.content)
        if request.edit.summary is not None:
            updates["summary"] = request.edit.summary
        if request.edit.name is not None:
            updates["name"] = request.edit.name
        outcome.append("edited")
    fallback_project = await _writer_project(db, target)
    memory = await _lock_memory(db, request, through)
    if memory is None:
        raise ReviewConflict(request.key, f"{request.key} is deleted; refuse restores it", latest_revision=through.id)
    if request.narrow is not None:
        updates |= _narrow_memory(memory, request.narrow, fallback_project)
        outcome.append("narrowed")
    await MemoryRepository().update(memory.id, db=db, action="rework", changed_by=_changed_by("rework"),
                                    change_reason=request.note or "Reworked in context review", **updates)
    revision = await _latest_memory_revision(db, request.target_id)
    return " and ".join(outcome), (str(revision.id), revision.created_at)


async def _writer_project(db: AsyncSession, target: Fold) -> str | None:
    """The project the latest unreviewed writer was working in (from its context delivery), if known."""
    writers = await resolve_writers(db, [WriterView(step) for step in target.pending])
    return next((w.project for w in reversed(writers) if w.project), None)


def _narrow_memory(memory: Memory, narrow: Narrow, fallback_project: str | None) -> dict[str, Any]:
    if narrow.to == "session":
        return {"status": "archived"}
    updates: dict[str, Any] = {}
    project = narrow.project_id or (memory.scope_id if memory.scope == "project" else None) or fallback_project
    if narrow.to == "project" or narrow.project_id:
        if not project:
            raise HTTPException(422, "Name the project to narrow to")
        updates |= {"scope": "project", "scope_id": project}
    if narrow.to == "role":
        applicability = dict(memory.applicability or {})
        applicability["audience_tags"] = [WORK_ROLE_TAG_PREFIX + str(narrow.role)]
        updates["applicability"] = applicability
    return updates


# ---------------------------------------------------------------------------------------------------------------
# Prompt


async def _lock_prompt(db: AsyncSession, item: ReviewItem, through: Step) -> Prompt | None:
    prompt = await lock_prompt_by_slug(db, item.target_id)
    latest = (await db.execute(
        select(PromptRevision.id).where(PromptRevision.prompt_slug == item.target_id)
        .order_by(PromptRevision.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if str(latest) != through.id:
        raise ReviewConflict(item.key, f"{item.key} changed since you looked; reload", latest_revision=str(latest))
    return prompt


async def _refuse_prompt(
    db: AsyncSession, item: ReviewItem, target: Fold, through: Step, note: str | None, touched: Touched,
) -> tuple[str, tuple[str, datetime] | None]:
    base = target.base
    reason = note or "Refused in context review"
    if base is None or base.action == "delete":
        prompt = await _lock_prompt(db, item, through)
        if prompt is None:
            return "nothing to undo", None
        prompt.enabled = False
        _sync_owned_agent_system_prompt_mirror(prompt)
        await db.flush()
        revision = await record_prompt_revision(db, prompt, action="refuse", changed_by=_changed_by("refuse"),
                                                change_reason=reason)
        touched.prompts.append(prompt)
        return "disabled", (str(revision.id), revision.created_at)
    try:
        prompt = await restore_prompt_revision(db, item.target_id, base.id, expected_revision_id=through.id,
                                               changed_by=_changed_by("refuse"), change_reason=reason, commit=False)
    except PromptRevisionConflictError as exc:
        raise ReviewConflict(item.key, str(exc), latest_revision=through.id) from exc
    if prompt is None:  # pragma: no cover - base came from this history
        raise HTTPException(404, f"{item.key}: revision {base.id[:8]} is gone")
    touched.prompts.append(prompt)
    revision = (await db.execute(
        select(PromptRevision).where(PromptRevision.prompt_slug == item.target_id)
        .order_by(PromptRevision.created_at.desc()).limit(1)
    )).scalar_one()
    return "restored", (str(revision.id), revision.created_at)


async def _rework_prompt(
    db: AsyncSession, request: ReworkRequest, through: Step, touched: Touched,
) -> tuple[str, tuple[str, datetime]]:
    prompt = await _lock_prompt(db, request, through)
    if prompt is None:
        raise ReviewConflict(request.key, f"{request.key} is deleted; refuse restores it", latest_revision=through.id)
    outcome = []
    if request.edit is not None:
        if request.edit.content is not None:
            prompt.content = request.edit.content
        if request.edit.summary is not None:
            prompt.description = request.edit.summary
        if request.edit.name is not None:
            prompt.name = request.edit.name
        outcome.append("edited")
    if request.narrow is not None:
        _narrow_prompt(prompt, request.narrow)
        outcome.append("narrowed")
    _sync_owned_agent_system_prompt_mirror(prompt)
    await db.flush()
    revision = await record_prompt_revision(db, prompt, action="rework", changed_by=_changed_by("rework"),
                                            change_reason=request.note or "Reworked in context review")
    touched.prompts.append(prompt)
    return " and ".join(outcome), (str(revision.id), revision.created_at)


def _narrow_prompt(prompt: Prompt, narrow: Narrow) -> None:
    if narrow.to == "session":
        prompt.enabled = False
        return
    policy = source_policy(prompt).model_dump()
    project = narrow.project_id or (policy["targets"][0] if policy["scope"] == "project" and policy["targets"] else None)
    if narrow.to == "project" or narrow.project_id:
        if not project:
            raise HTTPException(422, "Name the project to narrow to")
        policy |= {"scope": "project", "targets": [project]}
    if narrow.to == "role":
        policy["applicability"] = {**policy.get("applicability", {}),
                                   "audience_tags": [WORK_ROLE_TAG_PREFIX + str(narrow.role)]}
    try:
        prompt.context_policy = ContextPolicy.model_validate(policy).model_dump()
    except ValueError as exc:
        raise HTTPException(422, f"Narrowed policy is invalid: {exc}") from exc
    if policy["scope"] != "global":
        prompt.is_global = False


# ---------------------------------------------------------------------------------------------------------------
# Placement


async def _refuse_placement(
    db: AsyncSession, item: ReviewItem, target: Fold, through: Step, note: str | None,
) -> tuple[str, tuple[str, datetime]]:
    from app.services.context_governance import (
        changed_placement_source_ids,
        placement_snapshot,
        record,
    )

    profile, project = parse_placement_key(item.target_id)
    await lock_placement_layer(db, profile, project)
    layer = layer_request(item.target_id)
    current = await placement_snapshot(db, layer)
    seen = (through.row.payload or {}).get("after_placements") or []
    if semantic_hash(current) != semantic_hash(seen):
        raise ReviewConflict(item.key, f"{item.key}: placement rules changed since you looked; reload",
                             latest_revision=through.id)
    restored = (target.pending[0].row.payload or {}).get("before_placements") or []
    await db.execute(delete(RuntimeContextOverride).where(
        RuntimeContextOverride.consumer_profile == profile,
        RuntimeContextOverride.project_id.is_(None) if project is None else RuntimeContextOverride.project_id == project,
    ))
    for snapshot in restored:
        db.add(RuntimeContextOverride(**snapshot, consumer_profile=profile, project_id=project))
    await db.flush()
    after = await placement_snapshot(db, layer)
    record_id = await record(db, "change", attribute(_changed_by("refuse")) or _changed_by("refuse"), {
        "reason": note or "Refused placement change in context review", "changes": [],
        "context": layer.model_dump(mode="json"),
        "placement_source_ids": changed_placement_source_ids(current, after),
        "before_placements": current, "after_placements": after,
    })
    from app.models.context_governance import ContextRecord

    saved = await db.get(ContextRecord, record_id)
    assert saved is not None
    await db.refresh(saved, attribute_names=["created_at"])
    return "restored", (record_id, max(saved.created_at, through.at))
