"""The context review queue: unreviewed changes to agent context, one row per changed target.

Agents keep writing with no gate; the owner reviews afterwards. A change queues when a revision of a memory or
prompt, or a placement change record, was written by an agent or another client after the target's last review,
unless it stays in the archive on both sides (a memory that was and still is archived or tier 4, a prompt that was
and still is disabled). Owner writes (the owner token and the owner UIs) never queue. System writes (redundancy
consolidation, scope normalization, retirement: writer_kind system) never queue either; they stay in history and the
last week of them is listed separately as ``automatic``, never counted as waiting. Revisions written before writer
capture (writer_kind NULL) never queue. All unreviewed revisions of one target fold into one row whose diff runs from
the revision before the first of them (``base``) to the live state; owner or system writes after the first of them
are listed in ``also_undoes`` because a refuse puts them back too. A prompt's history follows its row
(``prompt_revisions.prompt_id``) across renames, keyed by its current slug; a deleted prompt's history (prompt_id
cleared) is keyed by slug. Reach (who receives it, starts per day, subagents included) comes from the recorded
deliveries that carried the target's block since the change (before it, for a delete or archive); with none yet it is
unknown, not zero. Rows written by the same agent session link to each other, so refusing a create also shows that
session's deletes and supersedes.
"""

from __future__ import annotations

import uuid as _uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, text
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
SYSTEM = "system"
UNQUEUED_WRITERS = (OWNER, SYSTEM)  # their writes stay in history but never wait for review
AUTOMATIC_LIMIT = 100
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
    pending: list[Step] = field(default_factory=list)  # unreviewed agent or client, non-archive steps
    base: Step | None = None  # the step before the first pending one
    latest: Step | None = None
    also_undoes: list[Step] = field(default_factory=list)  # owner or system steps after the first pending one

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.target_id}"


def fold(kind: TargetKind, target_id: str, steps: list[Step], covered_until: datetime | None) -> Fold:
    steps = sorted(steps, key=lambda s: (s.at, s.version or 0))
    result = Fold(kind, target_id, steps, covered_until, latest=steps[-1] if steps else None)
    for index, step in enumerate(steps):
        if covered_until is not None and step.at <= covered_until:
            continue
        if step.writer_kind is None or step.writer_kind in UNQUEUED_WRITERS:
            continue
        previous = steps[index - 1] if index else None
        if step.archived and (previous is None or previous.archived):
            continue  # stays in the archive: never delivered before or after
        if not result.pending:
            result.base = previous
        result.pending.append(step)
    if result.pending:
        start = next(i for i, s in enumerate(steps) if s is result.pending[0])
        queued = {id(s) for s in result.pending}
        result.also_undoes = [s for s in steps[start + 1:]
                              if id(s) not in queued and s.writer_kind in UNQUEUED_WRITERS]
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
        "slug": getattr(row, "prompt_slug", None) or getattr(row, "slug", None),
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


_QUEUED_WRITER_SQL = "r.writer_kind IS NOT NULL AND r.writer_kind NOT IN (" + ", ".join(
    f"'{kind}'" for kind in UNQUEUED_WRITERS) + ")"


async def _memory_candidates(db: AsyncSession) -> list[str]:
    rows = await db.execute(text(
        f"SELECT DISTINCT r.memory_uuid FROM memory_revisions r WHERE {_QUEUED_WRITER_SQL}"
        " AND " + _unreviewed_clause("memory", "r.memory_uuid", "r.created_at")
    ))
    return [str(value) for value in rows.scalars()]


async def _prompt_candidates(db: AsyncSession) -> list[str]:
    """Current slugs (a renamed prompt's revisions count under its new slug) with unreviewed queued writes.

    A superset: the review join is by slug, the exact cover (by revision) is checked in the fold.
    """
    target = "COALESCE(p.slug, r.prompt_slug)"
    rows = await db.execute(text(
        f"SELECT DISTINCT {target} FROM prompt_revisions r LEFT JOIN prompts p ON p.id = r.prompt_id"
        f" WHERE {_QUEUED_WRITER_SQL} AND " + _unreviewed_clause("prompt", target, "r.created_at")
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
    """One fold per current slug. A live prompt's history is every revision of its row (``prompt_id``), whatever
    slug it had then, so a rename stays one row with the old slug as its base. Revisions whose row is gone
    (``prompt_id`` cleared by a delete) group by slug. Reviews count through the revision they decided."""
    if not slugs:
        return []
    slug_by_id = {int(prompt_id): str(slug) for prompt_id, slug in (await db.execute(
        select(Prompt.id, Prompt.slug).where(Prompt.slug.in_(slugs)))).all()}
    revisions = (await db.execute(select(PromptRevision).where(or_(
        PromptRevision.prompt_id.in_(list(slug_by_id)),
        and_(PromptRevision.prompt_id.is_(None), PromptRevision.prompt_slug.in_(slugs)),
    )))).scalars().all()
    by_target: dict[str, list[Step]] = defaultdict(list)
    for revision in revisions:
        deleted = revision.action == "delete"
        key = slug_by_id.get(revision.prompt_id) if revision.prompt_id is not None else revision.prompt_slug
        if key is None:
            continue
        by_target[key].append(Step(
            id=str(revision.id), at=revision.created_at, action=revision.action, writer_kind=revision.writer_kind,
            writer_delivery=revision.writer_delivery, writer_session=revision.writer_session,
            archived=deleted or not revision.enabled, state=None if deleted else _prompt_state(revision), row=revision,
        ))
    covered = await _reviews_through(db, "prompt", by_target)
    return [fold("prompt", slug, by_target.get(slug, []), covered.get(slug)) for slug in slugs]


async def _reviews_through(db: AsyncSession, kind: TargetKind, by_target: dict[str, list[Step]]) -> dict[str, datetime]:
    """How far each target's reviews reach, matched by the revision each review decided (not by name)."""
    owner_of = {step.id: target for target, steps in by_target.items() for step in steps}
    if not owner_of:
        return {}
    rows = (await db.execute(
        select(ContextChangeReview.through_revision, func.max(ContextChangeReview.covered_until))
        .where(ContextChangeReview.target_kind == kind, ContextChangeReview.through_revision.in_(list(owner_of)))
        .group_by(ContextChangeReview.through_revision)
    )).all()
    covered: dict[str, datetime] = {}
    for through, until in rows:
        target = owner_of[str(through)]
        covered[target] = max(covered.get(target, until), until)
    return covered


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


async def placement_folds(
    db: AsyncSession, layers: list[str] | None = None, by_layer: dict[str, list[ContextRecord]] | None = None,
) -> list[Fold]:
    by_layer = await _placement_records(db) if by_layer is None else by_layer
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
    """Who received the target in a window of recorded deliveries (subagents included).

    The window runs from the change to now (at most ``REACH_DAYS``), or covers the ``REACH_DAYS`` before the change
    when the change stops delivery (delete, archive, disable). Per-day rates divide by the window, at least one day.
    """

    since: datetime
    until: datetime
    days: float
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


class LookInto(BaseModel):
    """Nightshift's hand-off of a row to an agent ("Look into it"): its state, one owner-facing line, the Aico window.

    state: queued | working (open: asking again starts nothing) | fixed | nothing | needs-you | failed | ended, or
    unknown when Nightshift did not answer (never an error for the page)."""

    state: str
    text: str = ""
    link: str = ""
    id: str | None = None
    revision: str | None = None


class LaterWrite(BaseModel):
    """An owner or system write after the first unreviewed change; refusing the row undoes it too."""

    revision: str
    at: datetime
    writer_kind: str | None
    action: str
    by: str | None


class AutomaticChange(BaseModel):
    """A system write (consolidation, scope normalization, retirement): listed, never waiting for review."""

    key: str
    target_kind: TargetKind
    target_id: str
    title: str
    action: str
    at: datetime
    revision: str
    by: str | None
    reason: str | None


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
    reach: Reach | None  # None: unknown (no recorded delivery since the change yet), not zero
    also_undoes: list[LaterWrite]  # owner or system writes a refuse would put back too
    writers: list[RevisionWriter]
    sessions: list[str]
    linked: list[str]  # keys of other unreviewed rows written by the same sessions
    hint: ReviewHint | None
    lookinto: LookInto | None = None  # set by the API from one Nightshift read; None: no hand-off for this revision
    lookinto_project: str | None = None  # the project a look-in on this row runs in (set by the API)


class QueueSummary(BaseModel):
    count: int
    by_kind: dict[str, int]
    global_count: int
    tokens_per_day: int  # rows with known reach only
    unknown_reach: int = 0  # rows whose reach is not known yet


class Queue(BaseModel):
    rows: list[QueueRow]
    summary: QueueSummary
    automatic: list[AutomaticChange] = []  # the last REACH_DAYS of system writes; not counted in summary


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


Window = tuple[datetime, datetime]


def reach_window(first_at: datetime, *, stops_delivery: bool, now: datetime) -> Window:
    if stops_delivery:
        return first_at - timedelta(days=REACH_DAYS), first_at
    return max(first_at, now - timedelta(days=REACH_DAYS)), now


async def source_reach(db: AsyncSession, windows: dict[str, Window]) -> dict[str, Reach]:
    """Reach per ``type:id`` source key from the deliveries in its window; absent when unknown."""
    if not windows or not await _table_exists(db, "context_deliveries"):
        return {}
    keys = list(windows)
    subagents = await _table_exists(db, "usage_sessions")
    join = ("LEFT JOIN usage_sessions u ON u.delivery_id = hits.delivery_id AND u.launch_mode LIKE 'subagent:%'"
            if subagents else "")
    rows = (await db.execute(text(
        "WITH win AS (SELECT * FROM unnest(CAST(:keys AS text[]), CAST(:sinces AS timestamptz[]),"
        " CAST(:untils AS timestamptz[])) AS w(key, since, until)),"
        " hits AS (SELECT DISTINCT d.delivery_id, d.surface, d.work_role, w.key"
        " FROM context_deliveries d CROSS JOIN LATERAL jsonb_array_elements(d.blocks) b"
        " JOIN win w ON w.key = (b->>'source_type') || ':' || (b->>'source_id')"
        " WHERE d.generated_at >= :earliest AND d.generated_at >= w.since AND d.generated_at < w.until)"
        " SELECT hits.key, hits.surface, hits.work_role, count(DISTINCT hits.delivery_id) AS starts,"
        f" {'count(u.delivery_id)' if subagents else '0'} AS subagents FROM hits {join}"
        " GROUP BY hits.key, hits.surface, hits.work_role"
    ), {"keys": keys, "sinces": [windows[k][0] for k in keys], "untils": [windows[k][1] for k in keys],
        "earliest": min(w[0] for w in windows.values())})).all()
    return _reach_from_rows(windows, rows)


async def layer_reach(db: AsyncSession, windows: dict[str, Window]) -> dict[str, Reach]:
    """Reach of a placement layer: the deliveries built for its profile (and project, when it has one)."""
    if not windows or not await _table_exists(db, "context_deliveries"):
        return {}
    result: dict[str, Reach] = {}
    for layer, (since, until) in windows.items():
        profile, project = parse_placement_key(layer)
        rows = (await db.execute(text(
            "SELECT :layer AS key, surface, work_role, count(*) AS starts, 0 AS subagents FROM context_deliveries"
            " WHERE generated_at >= :since AND generated_at < :until AND profile = :profile"
            " AND (CAST(:project AS text) IS NULL OR project_id = :project) GROUP BY surface, work_role"
        ), {"layer": layer, "since": since, "until": until, "profile": profile, "project": project})).all()
        result.update(_reach_from_rows({layer: (since, until)}, rows))
    return result


def _reach_from_rows(windows: dict[str, Window], rows: Any) -> dict[str, Reach]:
    """Known reach per key. No delivery in a window shorter than REACH_DAYS is unknown (absent), not zero."""
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[str(row[0])].append(row)
    out: dict[str, Reach] = {}
    for key, (since, until) in windows.items():
        receivers = sorted((Receiver(harness=str(r[1]), role=r[2], starts=int(r[3])) for r in grouped.get(key, [])),
                           key=lambda r: -r.starts)
        starts = sum(r.starts for r in receivers)
        subagent_starts = sum(int(r[4] or 0) for r in grouped.get(key, []))
        span = (until - since).total_seconds() / 86400
        if starts == 0 and span < REACH_DAYS:
            continue
        days = max(span, 1.0)
        out[key] = Reach(since=since, until=until, days=round(days, 2), starts=starts, subagent_starts=subagent_starts,
                         starts_per_day=round((starts + subagent_starts) / days, 1), receivers=receivers)
    return out


def _stops_delivery(before: dict[str, Any] | None, after: dict[str, Any] | None) -> bool:
    return _delivered_tokens(after) == 0 and _delivered_tokens(before) > 0


def later_writes(item: Fold) -> list[LaterWrite]:
    return [LaterWrite(revision=s.id, at=s.at, writer_kind=s.writer_kind, action=s.action,
                       by=getattr(s.row, "changed_by", None) or getattr(s.row, "actor", None))
            for s in item.also_undoes]


async def automatic_changes(
    db: AsyncSession, placement_records: dict[str, list[ContextRecord]], *, days: int = REACH_DAYS,
) -> list[AutomaticChange]:
    """System writes of the last ``days`` days that left or entered delivery (archive-to-archive skipped)."""
    since = datetime.now(UTC) - timedelta(days=days)
    params = {"since": since, "limit": AUTOMATIC_LIMIT}
    memory_rows = (await db.execute(text(
        "SELECT * FROM (SELECT r.id, r.memory_uuid, r.action, r.created_at, r.changed_by, r.change_reason,"
        " COALESCE(r.summary, r.name) AS title, r.writer_kind,"
        f" (r.action = 'delete' OR r.status <> 'active' OR COALESCE(r.tier, 3) >= {ARCHIVE_TIER}) AS archived,"
        f" LAG(r.action = 'delete' OR r.status <> 'active' OR COALESCE(r.tier, 3) >= {ARCHIVE_TIER})"
        " OVER (PARTITION BY r.memory_uuid ORDER BY r.created_at, r.version) AS was_archived"
        " FROM memory_revisions r WHERE r.memory_uuid IN (SELECT memory_uuid FROM memory_revisions"
        f" WHERE writer_kind = '{SYSTEM}' AND created_at >= :since)) x"
        f" WHERE x.writer_kind = '{SYSTEM}' AND x.created_at >= :since"
        " AND NOT (x.archived AND COALESCE(x.was_archived, true)) ORDER BY x.created_at DESC LIMIT :limit"
    ), params)).all()
    prompt_rows = (await db.execute(text(
        "SELECT * FROM (SELECT r.id, r.prompt_slug, r.action, r.created_at, r.changed_by, r.change_reason,"
        " r.writer_kind, (r.action = 'delete' OR NOT r.enabled) AS archived,"
        " LAG(r.action = 'delete' OR NOT r.enabled) OVER (PARTITION BY COALESCE(CAST(r.prompt_id AS text),"
        " r.prompt_slug) ORDER BY r.created_at) AS was_archived"
        " FROM prompt_revisions r WHERE COALESCE(CAST(r.prompt_id AS text), r.prompt_slug) IN"
        " (SELECT COALESCE(CAST(prompt_id AS text), prompt_slug) FROM prompt_revisions"
        f" WHERE writer_kind = '{SYSTEM}' AND created_at >= :since)) x"
        f" WHERE x.writer_kind = '{SYSTEM}' AND x.created_at >= :since"
        " AND NOT (x.archived AND COALESCE(x.was_archived, true)) ORDER BY x.created_at DESC LIMIT :limit"
    ), params)).all()
    changes = [AutomaticChange(key=f"memory:{r.memory_uuid}", target_kind="memory", target_id=str(r.memory_uuid),
                               title=str(r.title or r.memory_uuid)[:200], action=r.action, at=r.created_at,
                               revision=str(r.id), by=r.changed_by, reason=r.change_reason) for r in memory_rows]
    changes += [AutomaticChange(key=f"prompt:{r.prompt_slug}", target_kind="prompt", target_id=r.prompt_slug,
                                title=r.prompt_slug, action=r.action, at=r.created_at, revision=str(r.id),
                                by=r.changed_by, reason=r.change_reason) for r in prompt_rows]
    for layer, records in placement_records.items():
        for record in records:
            step = _placement_step(record)
            if step.writer_kind == SYSTEM and step.at >= since:
                changes.append(AutomaticChange(
                    key=f"placement:{layer}", target_kind="placement", target_id=layer, title=f"{layer} placements",
                    action="placement", at=step.at, revision=record.id, by=record.actor,
                    reason=(record.payload or {}).get("reason")))
    changes.sort(key=lambda c: c.at, reverse=True)
    return changes[:AUTOMATIC_LIMIT]


async def build_queue(
    db: AsyncSession, *, session: str | None = None, kind: TargetKind | None = None, automatic: bool = True,
) -> Queue:
    """Every unreviewed change, newest first. ``session`` and ``kind`` filter rows after linking.

    ``automatic`` adds the separate list of recent system writes (skipped for a session filter)."""
    memory = await memory_folds(db, await _memory_candidates(db))
    prompts = await prompt_folds(db, await _prompt_candidates(db))
    placement_records = await _placement_records(db)
    placements = await placement_folds(db, by_layer=placement_records)
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

    drafts: list[tuple[Fold, dict[str, Any] | None, dict[str, Any] | None, str, int | None, ReviewHint | None]] = []
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
        drafts.append((item, before, after, str(title), version, hint))

    now = datetime.now(UTC)
    windows = {draft[0].key: reach_window(draft[0].pending[0].at, stops_delivery=_stops_delivery(draft[1], draft[2]),
                                          now=now) for draft in drafts}
    reach = await source_reach(db, {k: w for k, w in windows.items() if not k.startswith("placement:")})
    reach |= {f"placement:{k}": v for k, v in (await layer_reach(db, {
        k.removeprefix("placement:"): w for k, w in windows.items() if k.startswith("placement:")})).items()}

    rows: list[QueueRow] = []
    for item, before, after, title, version, hint in drafts:
        assert item.latest is not None
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
            reach=row_reach, also_undoes=later_writes(item),
            writers=_distinct_writers(writers_by_step[id(s)] for s in item.pending),
            sessions=sessions_by_key[item.key], linked=linked, hint=hint,
        ))
    rows.sort(key=lambda r: r.last_at, reverse=True)
    if session is not None:
        rows = [r for r in rows if session in r.sessions]
    if kind is not None:
        rows = [r for r in rows if r.target_kind == kind]
    system = await automatic_changes(db, placement_records) if automatic and session is None else []
    if kind is not None:
        system = [c for c in system if c.target_kind == kind]
    return Queue(rows=rows, summary=summarize(rows), automatic=system)


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
                        tokens_per_day=sum(r.tokens_per_day or 0 for r in rows),
                        unknown_reach=sum(1 for r in rows if r.reach is None))


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
