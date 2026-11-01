"""The context review queue: unreviewed changes to agent context, one row per changed target.

Agents keep writing with no gate; the owner reviews afterwards. A change queues when a revision of a memory or
prompt, or a placement change record, was written by anyone but the owner (writer_kind owner covers the owner token
and the internal UI) after the target's last review, unless it stays in the archive on both sides (a memory that was
and still is archived or tier 4, a prompt that was and still is disabled). Revisions written before writer capture
(writer_kind NULL) never queue. All unreviewed revisions of one target fold into one row whose diff runs from the
revision before the first of them (``base``) to the live state. Reach (who receives it, starts per day, subagents
included) comes from the recorded deliveries that carried the target's block. Rows written by the same agent session
link to each other, so refusing a create also shows that session's deletes and supersedes.
"""

from __future__ import annotations

import uuid as _uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context_change_review import ContextChangeReview
from app.models.context_governance import ContextRecord
from app.models.memory_unified import Memory, MemoryRevision
from app.models.prompt import Prompt, PromptRevision
from app.services.context_writer import RevisionWriter, resolve_writers
from app.services.memory.applicability import WORK_ROLE_TAG_PREFIX
from app.services.memory.budget import count_tokens

TargetKind = Literal["memory", "prompt", "placement"]
ChangeKind = Literal["create", "update", "delete", "archive", "scope", "placement"]
OWNER = "owner"
ARCHIVE_TIER = 4
REACH_DAYS = 7
_TIER_NAMES = {1: "mandate", 2: "guardrail", 3: "reference", 4: "archive"}
# The review agent's verdict, shown as a hint next to the owner's choice.
_HINT_LABELS = {"archive": "looks session-only", "merge": "looks like a duplicate", "retarget": "looks mis-scoped",
                "keep": "looks fine"}


def placement_key(profile: str, project_id: str | None) -> str:
    return f"{profile}|{project_id or ''}"


def parse_placement_key(target_id: str) -> tuple[str, str | None]:
    profile, _, project = target_id.partition("|")
    return profile, project or None


@dataclass
class Step:
    """One recorded change of a target: a memory or prompt revision, or a placement change record."""

    id: str
    at: datetime
    action: str
    writer_kind: str | None
    writer_delivery: str | None
    writer_session: str | None
    archived: bool
    state: dict[str, Any] | None  # what the target looked like after this step (None: deleted)
    version: int | None = None
    row: Any = None


@dataclass
class Fold:
    """A target's history split at its last review."""

    kind: TargetKind
    target_id: str
    steps: list[Step]
    covered_until: datetime | None
    pending: list[Step] = field(default_factory=list)  # unreviewed non-owner, non-archive steps
    base: Step | None = None  # the step before the first pending one
    latest: Step | None = None

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.target_id}"


def fold(kind: TargetKind, target_id: str, steps: list[Step], covered_until: datetime | None) -> Fold:
    steps = sorted(steps, key=lambda s: (s.at, s.version or 0))
    result = Fold(kind, target_id, steps, covered_until, latest=steps[-1] if steps else None)
    for index, step in enumerate(steps):
        if covered_until is not None and step.at <= covered_until:
            continue
        if step.writer_kind is None or step.writer_kind == OWNER:
            continue
        previous = steps[index - 1] if index else None
        if step.archived and (previous is None or previous.archived):
            continue  # stays in the archive: never delivered before or after
        if not result.pending:
            result.base = previous
        result.pending.append(step)
    return result


def _memory_archived(row: Memory | MemoryRevision | None, action: str | None = None) -> bool:
    return row is None or action == "delete" or row.status != "active" or int(row.tier or 3) >= ARCHIVE_TIER


def _memory_state(row: Memory | MemoryRevision) -> dict[str, Any]:
    roles = [t[len(WORK_ROLE_TAG_PREFIX):] for t in (row.applicability or {}).get("audience_tags", [])
             if isinstance(t, str) and t.startswith(WORK_ROLE_TAG_PREFIX)]
    return {
        "name": row.name, "summary": row.summary, "content": row.content, "scope": row.scope,
        "scope_id": row.scope_id, "tier": row.tier, "status": row.status, "context_kind": row.context_kind,
        "applicability": dict(row.applicability or {}), "roles": roles,
        "trigger_task_types": list(row.trigger_task_types or []), "trigger_phases": list(row.trigger_phases or []),
        "render_mode": row.render_mode, "tokens": count_tokens(row.content or ""),
    }


def _prompt_state(row: Prompt | PromptRevision) -> dict[str, Any]:
    policy = row.context_policy if isinstance(row.context_policy, dict) else None
    scope = (policy or {}).get("scope") or ("global" if row.is_global else "unassigned")
    roles = [t[len(WORK_ROLE_TAG_PREFIX):] for t in ((policy or {}).get("applicability") or {}).get("audience_tags", [])
             if isinstance(t, str) and t.startswith(WORK_ROLE_TAG_PREFIX)]
    return {
        "name": getattr(row, "prompt_name", None) or getattr(row, "name", None), "summary": row.description,
        "content": row.content, "scope": scope, "scope_id": ",".join((policy or {}).get("targets") or []) or None,
        "status": "active" if row.enabled else "disabled", "prompt_type": row.prompt_type, "roles": roles,
        "context_policy": policy, "tokens": count_tokens(row.content or ""),
    }


def scope_label(state: dict[str, Any] | None) -> str:
    """``global reference``, ``project agent-hub mandate role implementation``, ``archived``, ``deleted``."""
    if state is None:
        return "deleted"
    if state.get("status") not in (None, "active"):
        return str(state["status"])
    if "placements" in state:
        return f"{len(state['placements'])} placement rules"
    parts = [state.get("scope") or "unassigned"]
    if state.get("scope_id"):
        parts.append(str(state["scope_id"]))
    if state.get("tier") is not None:
        parts.append(_TIER_NAMES.get(int(state["tier"]), str(state["tier"])))
    if state.get("roles"):
        parts.append("role " + ",".join(state["roles"]))
    return " ".join(parts)


async def latest_reviews(db: AsyncSession, kind: TargetKind, target_ids: list[str]) -> dict[str, datetime]:
    """How far each target's reviews reach (the latest covered_until; decisions never move it back)."""
    if not target_ids:
        return {}
    rows = (await db.execute(
        select(ContextChangeReview.target_id, func.max(ContextChangeReview.covered_until))
        .where(ContextChangeReview.target_kind == kind, ContextChangeReview.target_id.in_(target_ids))
        .group_by(ContextChangeReview.target_id)
    )).all()
    return {str(target_id): covered for target_id, covered in rows}


def _unreviewed_clause(kind: TargetKind, target_column: str, at_column: str) -> str:
    return (
        f"NOT EXISTS (SELECT 1 FROM context_change_reviews ccr WHERE ccr.target_kind = '{kind}'"
        f" AND ccr.target_id = {target_column} AND ccr.covered_until >= {at_column})"
    )


async def _memory_candidates(db: AsyncSession) -> list[str]:
    rows = await db.execute(text(
        "SELECT DISTINCT r.memory_uuid FROM memory_revisions r WHERE r.writer_kind IS NOT NULL"
        f" AND r.writer_kind <> '{OWNER}' AND " + _unreviewed_clause("memory", "r.memory_uuid", "r.created_at")
    ))
    return [str(value) for value in rows.scalars()]


async def _prompt_candidates(db: AsyncSession) -> list[str]:
    rows = await db.execute(text(
        "SELECT DISTINCT r.prompt_slug FROM prompt_revisions r WHERE r.writer_kind IS NOT NULL"
        f" AND r.writer_kind <> '{OWNER}' AND " + _unreviewed_clause("prompt", "r.prompt_slug", "r.created_at")
    ))
    return [str(value) for value in rows.scalars()]


async def memory_folds(db: AsyncSession, memory_uuids: list[str]) -> list[Fold]:
    if not memory_uuids:
        return []
    revisions = (await db.execute(
        select(MemoryRevision).where(MemoryRevision.memory_uuid.in_(memory_uuids))
    )).scalars().all()
    by_target: dict[str, list[Step]] = defaultdict(list)
    for revision in revisions:
        deleted = revision.action == "delete"
        by_target[revision.memory_uuid].append(Step(
            id=str(revision.id), at=revision.created_at, action=revision.action, writer_kind=revision.writer_kind,
            writer_delivery=revision.writer_delivery, writer_session=revision.writer_session,
            archived=_memory_archived(revision, revision.action), state=None if deleted else _memory_state(revision),
            version=revision.version, row=revision,
        ))
    covered = await latest_reviews(db, "memory", memory_uuids)
    return [fold("memory", uid, by_target.get(uid, []), covered.get(uid)) for uid in memory_uuids]


async def prompt_folds(db: AsyncSession, slugs: list[str]) -> list[Fold]:
    if not slugs:
        return []
    revisions = (await db.execute(
        select(PromptRevision).where(PromptRevision.prompt_slug.in_(slugs))
    )).scalars().all()
    by_target: dict[str, list[Step]] = defaultdict(list)
    for revision in revisions:
        deleted = revision.action == "delete"
        by_target[revision.prompt_slug].append(Step(
            id=str(revision.id), at=revision.created_at, action=revision.action, writer_kind=revision.writer_kind,
            writer_delivery=revision.writer_delivery, writer_session=revision.writer_session,
            archived=deleted or not revision.enabled, state=None if deleted else _prompt_state(revision), row=revision,
        ))
    covered = await latest_reviews(db, "prompt", slugs)
    return [fold("prompt", slug, by_target.get(slug, []), covered.get(slug)) for slug in slugs]


def _placement_layer(record: ContextRecord) -> str | None:
    context = (record.payload or {}).get("context") or {}
    profile = context.get("consumer_profile")
    return placement_key(profile, context.get("project_id")) if profile else None


def _placement_step(record: ContextRecord) -> Step:
    writer = (record.payload or {}).get("writer") or {}
    return Step(
        id=record.id, at=record.created_at, action="placement", writer_kind=writer.get("writer_kind"),
        writer_delivery=writer.get("writer_delivery"), writer_session=writer.get("writer_session"),
        archived=False, state={"placements": record.payload.get("after_placements") or []}, row=record,
    )


async def _placement_records(db: AsyncSession) -> dict[str, list[ContextRecord]]:
    """Every context change record that changed placement rules, by placement layer."""
    records = (await db.execute(select(ContextRecord).where(
        ContextRecord.kind == "change",
        text("(context_records.payload::jsonb -> 'before_placements') IS DISTINCT FROM"
             " (context_records.payload::jsonb -> 'after_placements')"),
    ))).scalars().all()
    by_layer: dict[str, list[ContextRecord]] = defaultdict(list)
    for record in records:
        if (layer := _placement_layer(record)) is not None:
            by_layer[layer].append(record)
    return by_layer


async def placement_folds(db: AsyncSession, layers: list[str] | None = None) -> list[Fold]:
    by_layer = await _placement_records(db)
    targets = list(by_layer) if layers is None else layers
    covered = await latest_reviews(db, "placement", targets)
    return [fold("placement", layer, [_placement_step(r) for r in by_layer.get(layer, [])], covered.get(layer))
            for layer in targets]


async def target_fold(db: AsyncSession, kind: TargetKind, target_id: str) -> Fold:
    if kind == "memory":
        return (await memory_folds(db, [target_id]))[0]
    if kind == "prompt":
        return (await prompt_folds(db, [target_id]))[0]
    return (await placement_folds(db, [target_id]))[0]


# ---------------------------------------------------------------------------------------------------------------
# Queue rows


class Receiver(BaseModel):
    harness: str
    role: str | None
    starts: int


class Reach(BaseModel):
    """Who received the target in the last ``days`` days of recorded deliveries (subagents included)."""

    days: int
    starts: int
    subagent_starts: int
    starts_per_day: float
    receivers: list[Receiver]


class ReviewHint(BaseModel):
    """The AI review agent's last verdict on a memory; a hint, never the owner's decision."""

    label: str
    decision: str
    confidence: float | None = None
    reason: str | None = None
    reviewed_at: str | None = None


class QueueRow(BaseModel):
    key: str
    target_kind: TargetKind
    target_id: str
    title: str
    change: ChangeKind
    actions: list[str]
    first_at: datetime
    last_at: datetime
    base_revision: str | None
    through_revision: str  # send back to keep, rework or refuse; a newer one returns 409
    version: int | None  # memories.version now (expected_version), None for prompts and placements
    scope_before: str | None
    scope_after: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    delta_tokens: int | None
    tokens_per_day: int | None  # delta_tokens x starts per day; None when reach is unknown
    reach: Reach | None
    writers: list[RevisionWriter]
    sessions: list[str]
    linked: list[str]  # keys of other unreviewed rows written by the same sessions
    hint: ReviewHint | None


class QueueSummary(BaseModel):
    count: int
    by_kind: dict[str, int]
    global_count: int
    tokens_per_day: int


class Queue(BaseModel):
    rows: list[QueueRow]
    summary: QueueSummary


def session_of(step: Step) -> str | None:
    if step.writer_session:
        return step.writer_session
    return f"delivery:{step.writer_delivery}" if step.writer_delivery else None


def _change_kind(item: Fold, after: dict[str, Any] | None) -> ChangeKind:
    if item.kind == "placement":
        return "placement"
    base = None if item.base is None or item.base.action == "delete" else item.base.state
    if base is None:
        return "create"
    if after is None:
        return "delete"
    if after.get("status") != "active" or int(after.get("tier") or 3) >= ARCHIVE_TIER:
        return "archive"
    switches = ("scope", "scope_id", "tier", "status", "applicability", "context_policy", "trigger_task_types",
                "trigger_phases")
    if any(base.get(k) != after.get(k) for k in switches):
        return "scope"
    return "update"


def _hint(memory: Memory | None) -> ReviewHint | None:
    review = (memory.metadata_ or {}).get("last_review") if memory is not None else None
    if not isinstance(review, dict) or not review.get("decision"):
        return None
    decision = str(review["decision"])
    label = _HINT_LABELS.get(decision, decision.replace("_", " "))
    suggested = (review.get("suggested_applicability") or {}).get("scope")
    if decision == "retarget" and suggested:
        label = f"looks {suggested}-only"
    confidence = review.get("confidence")
    return ReviewHint(label=label, decision=decision, confidence=None if confidence is None else float(confidence),
                      reason=review.get("reason"), reviewed_at=review.get("reviewed_at"))


async def _table_exists(db: AsyncSession, name: str) -> bool:
    return bool((await db.execute(text(f"SELECT to_regclass('{name}') IS NOT NULL"))).scalar())


async def source_reach(db: AsyncSession, keys: list[str], *, days: int = REACH_DAYS) -> dict[str, Reach]:
    """Reach per ``type:id`` source key from recorded deliveries; absent when the deliveries table is missing."""
    if not keys or not await _table_exists(db, "context_deliveries"):
        return {}
    subagents = await _table_exists(db, "usage_sessions")
    join = ("LEFT JOIN usage_sessions u ON u.delivery_id = hits.delivery_id AND u.launch_mode LIKE 'subagent:%'"
            if subagents else "")
    rows = (await db.execute(text(
        "WITH hits AS (SELECT DISTINCT d.delivery_id, d.surface, d.work_role,"
        " (b->>'source_type') || ':' || (b->>'source_id') AS key"
        " FROM context_deliveries d CROSS JOIN LATERAL jsonb_array_elements(d.blocks) b"
        " WHERE d.generated_at >= :since"
        " AND (b->>'source_type') || ':' || (b->>'source_id') = ANY(CAST(:keys AS text[])))"
        " SELECT hits.key, hits.surface, hits.work_role, count(DISTINCT hits.delivery_id) AS starts,"
        f" {'count(u.delivery_id)' if subagents else '0'} AS subagents FROM hits {join}"
        " GROUP BY hits.key, hits.surface, hits.work_role"
    ), {"since": datetime.now(UTC) - timedelta(days=days), "keys": keys})).all()
    return _reach_from_rows(keys, rows, days)


async def layer_reach(db: AsyncSession, layers: list[str], *, days: int = REACH_DAYS) -> dict[str, Reach]:
    """Reach of a placement layer: the deliveries built for its profile (and project, when it has one)."""
    if not layers or not await _table_exists(db, "context_deliveries"):
        return {}
    result: dict[str, Reach] = {}
    for layer in layers:
        profile, project = parse_placement_key(layer)
        rows = (await db.execute(text(
            "SELECT :layer AS key, surface, work_role, count(*) AS starts, 0 AS subagents FROM context_deliveries"
            " WHERE generated_at >= :since AND profile = :profile AND (CAST(:project AS text) IS NULL"
            " OR project_id = :project) GROUP BY surface, work_role"
        ), {"layer": layer, "since": datetime.now(UTC) - timedelta(days=days), "profile": profile,
            "project": project})).all()
        result.update(_reach_from_rows([layer], rows, days))
    return result


def _reach_from_rows(keys: list[str], rows: Any, days: int) -> dict[str, Reach]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[str(row[0])].append(row)
    out: dict[str, Reach] = {}
    for key in keys:
        receivers = sorted((Receiver(harness=str(r[1]), role=r[2], starts=int(r[3])) for r in grouped.get(key, [])),
                           key=lambda r: -r.starts)
        starts = sum(r.starts for r in receivers)
        subagent_starts = sum(int(r[4] or 0) for r in grouped.get(key, []))
        out[key] = Reach(days=days, starts=starts, subagent_starts=subagent_starts,
                         starts_per_day=round((starts + subagent_starts) / days, 1), receivers=receivers)
    return out


async def build_queue(db: AsyncSession, *, session: str | None = None, kind: TargetKind | None = None) -> Queue:
    """Every unreviewed change, newest first. ``session`` and ``kind`` filter rows after linking."""
    memory = await memory_folds(db, await _memory_candidates(db))
    prompts = await prompt_folds(db, await _prompt_candidates(db))
    placements = await placement_folds(db)
    folds = [f for f in (*memory, *prompts, *placements) if f.pending and f.latest is not None]

    live_memories: dict[str, Memory] = {}
    memory_ids = [_uuid.UUID(f.target_id) for f in folds if f.kind == "memory"]
    if memory_ids:
        live_memories = {str(m.id): m for m in (await db.execute(
            select(Memory).where(Memory.id.in_(memory_ids)))).scalars()}
    live_prompts: dict[str, Prompt] = {}
    prompt_slugs = [f.target_id for f in folds if f.kind == "prompt"]
    if prompt_slugs:
        live_prompts = {p.slug: p for p in (await db.execute(
            select(Prompt).where(Prompt.slug.in_(prompt_slugs)))).scalars()}
    live_layers: dict[str, list[dict[str, Any]]] = {}
    for item in folds:
        if item.kind == "placement":
            live_layers[item.target_id] = await _live_placements(db, item.target_id)

    reach = await source_reach(db, [f.key for f in folds if f.kind != "placement"])
    reach |= {f"placement:{k}": v for k, v in
              (await layer_reach(db, [f.target_id for f in folds if f.kind == "placement"])).items()}

    pending_steps = [step for item in folds for step in item.pending]
    writers = iter(await resolve_writers(db, [WriterView(s) for s in pending_steps]))
    writers_by_step = {id(step): next(writers) for step in pending_steps}

    sessions_by_key: dict[str, list[str]] = {}
    keys_by_session: dict[str, set[str]] = defaultdict(set)
    for item in folds:
        sessions: list[str] = []
        for step in item.pending:
            name = session_of(step)
            if name is not None and name not in sessions:
                sessions.append(name)
                keys_by_session[name].add(item.key)
        sessions_by_key[item.key] = sessions

    rows: list[QueueRow] = []
    for item in folds:
        assert item.latest is not None
        if item.kind == "memory":
            live = live_memories.get(item.target_id)
            after = None if live is None else _memory_state(live)
            title = (live or item.latest.row).summary or (live or item.latest.row).name or item.target_id[:8]
            version = None if live is None else int(live.version or 1)
            hint = _hint(live)
        elif item.kind == "prompt":
            live_prompt = live_prompts.get(item.target_id)
            after = None if live_prompt is None else _prompt_state(live_prompt)
            title, version, hint = item.target_id, None, None
        else:
            after = {"placements": live_layers.get(item.target_id, [])}
            profile, project = parse_placement_key(item.target_id)
            title, version, hint = f"{profile} placements" + (f" in {project}" if project else ""), None, None
        before = None if item.base is None else item.base.state
        if item.kind == "placement":
            first = item.pending[0].row
            before = {"placements": (first.payload or {}).get("before_placements") or []}
        delta = None if item.kind == "placement" else _delivered_tokens(after) - _delivered_tokens(before)
        row_reach = reach.get(item.key)
        linked = sorted(set().union(*(keys_by_session[s] for s in sessions_by_key[item.key])) - {item.key}) \
            if sessions_by_key[item.key] else []
        rows.append(QueueRow(
            key=item.key, target_kind=item.kind, target_id=item.target_id, title=str(title)[:200],
            change=_change_kind(item, after),
            actions=[s.action for s in item.pending], first_at=item.pending[0].at, last_at=item.pending[-1].at,
            base_revision=None if item.base is None else item.base.id, through_revision=item.latest.id,
            version=version, scope_before=None if item.base is None else scope_label(before),
            scope_after=scope_label(after), before=before, after=after, delta_tokens=delta,
            tokens_per_day=None if row_reach is None or delta is None else round(delta * row_reach.starts_per_day),
            reach=row_reach, writers=_distinct_writers(writers_by_step[id(s)] for s in item.pending),
            sessions=sessions_by_key[item.key], linked=linked, hint=hint,
        ))
    rows.sort(key=lambda r: r.last_at, reverse=True)
    if session is not None:
        rows = [r for r in rows if session in r.sessions]
    if kind is not None:
        rows = [r for r in rows if r.target_kind == kind]
    return Queue(rows=rows, summary=summarize(rows))


def _delivered_tokens(state: dict[str, Any] | None) -> int:
    """Tokens a memory or prompt state adds to deliveries: none once deleted, archived or disabled."""
    if state is None or state.get("status") != "active" or int(state.get("tier") or 3) >= ARCHIVE_TIER:
        return 0
    return int(state.get("tokens") or 0)


def summarize(rows: list[QueueRow]) -> QueueSummary:
    by_kind: dict[str, int] = defaultdict(int)
    for row in rows:
        by_kind[row.target_kind] += 1
    global_count = sum(1 for r in rows if "global" in {(r.before or {}).get("scope"), (r.after or {}).get("scope")})
    return QueueSummary(count=len(rows), by_kind=dict(by_kind), global_count=global_count,
                        tokens_per_day=sum(r.tokens_per_day or 0 for r in rows))


def _distinct_writers(writers: Any) -> list[RevisionWriter]:
    seen: dict[tuple[Any, ...], RevisionWriter] = {}
    for writer in writers:
        seen.setdefault((writer.kind, writer.session, writer.delivery), writer)
    return list(seen.values())


class WriterView:
    def __init__(self, step: Step) -> None:
        self.writer_kind = step.writer_kind
        self.writer_delivery = step.writer_delivery
        self.writer_session = step.writer_session


async def _live_placements(db: AsyncSession, layer: str) -> list[dict[str, Any]]:
    from app.services.context_governance import placement_snapshot

    return await placement_snapshot(db, layer_request(layer))


def layer_request(layer: str) -> Any:
    from app.services.runtime_context import CanonicalContextDeliveryRequest

    profile, project = parse_placement_key(layer)
    return CanonicalContextDeliveryRequest(consumer_surface="context_change_review", consumer_profile=profile,
                                           project_id=project)
