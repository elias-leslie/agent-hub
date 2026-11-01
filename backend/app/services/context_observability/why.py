"""`why`: what moved a cell's first-turn context, split into harness, ours, config, brief and model.

Two windows around a step (the 7 days before it and the time after) are compared part by part. Ours is broken down to
the delivery blocks that were added, removed, grown or revised, with the memory or prompt writer from the revisions.
The harness part is blamed on a harness version or, with the version unchanged, on a config fingerprint change, named
after the knob files (context_knobs) that changed in git just before it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median_high
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .baseline import FirstTurn, load_first_turns
from .markers import Marker, knob_markers, view_markers
from .policy import Policy, load_policy
from .steps import (
    BASELINE_DAYS,
    ROLE_GROUPS,
    Found,
    Step,
    Window,
    cell_rows,
    find_step_rows,
    find_steps,
    in_cell,
    window,
)

MAX_TREND_DAYS = 90  # the longest range the Trend (and the steps list) takes
LOOKBACK_DAYS = MAX_TREND_DAYS + BASELINE_DAYS  # `why` reads this far back, so it finds every step a Trend range shows, with its week before
DEFAULT_STEPS_DAYS = 30
RECENT_HOURS = 24
BLOCK_LIMIT = 15
STEP_MATCH_S = 60  # `why --at` within this of a step's time is that step
PRESENT_SHARE = 0.5  # a block belongs to a window when at least this share of its deliveries carry it


@dataclass
class BlockChange:
    change: str  # added | removed | grown | shrunk | revised
    block: str
    kind: str | None
    scope: str | None
    label: str
    tokens_before: int
    tokens_after: int
    delta: int
    writer: dict[str, Any] | None = None  # newest revision of the source between the windows


@dataclass
class Why:
    harness: str
    role: str
    at: datetime | None
    kind: str  # the step kind (config | version | day), "at" for a chosen time, "recent" when no step was found
    cause: str  # ours | config | harness_version | harness | model | brief | mixed (two parts moved alike) | unknown (cannot be pinned down) | none (nothing moved)
    before: Window | None
    after: Window | None
    delta: int | None
    pct: float | None
    parts: dict[str, int | None] = field(default_factory=dict)  # change in harness / ours / brief / other
    version: dict[str, str | None] = field(default_factory=dict)
    config_fp: dict[str, str | None] = field(default_factory=dict)
    model: dict[str, str | None] = field(default_factory=dict)
    knobs: list[Marker] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    blocks: list[BlockChange] = field(default_factory=list)
    summary: str = ""
    changed: list[str] = field(default_factory=list)  # what changed at the step: model | config_fp | version


CHANGED_WORDS = {"config_fp": "request shape"}  # `changed` keeps the field name for callers; text says it in words


def _k(tokens: int | None) -> str:
    return "unknown" if tokens is None else f"{tokens / 1000:.1f}K"


def _signed(tokens: int | None) -> str:
    return "unknown" if tokens is None else f"{'+' if tokens >= 0 else '-'}{abs(tokens) / 1000:.1f}K"


def _diff(before: int | None, after: int | None) -> int | None:
    return None if before is None or after is None else after - before


async def _deliveries(db: AsyncSession, rows: list[FirstTurn]) -> list[tuple[str | None, list[dict[str, Any]]]]:
    ids = sorted({r.delivery_id for r in rows if r.delivery_id})
    if not ids:
        return []
    found = (await db.execute(text("SELECT project_id, blocks FROM context_deliveries WHERE delivery_id = ANY(:ids)"), {"ids": ids})).all()
    return [(r.project_id, list(r.blocks or [])) for r in found]


def _block_sets(found: list[tuple[str | None, list[dict[str, Any]]]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Blocks a window's bound deliveries carry: median tokens and the usual revision, for those in enough of them."""
    if not found:
        return {}
    per_block: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for _project, blocks in found:
        for block in blocks:
            per_block[(str(block.get("source_type")), str(block.get("source_id")), str(block.get("block_id")))].append(block)
    out = {}
    for key, items in per_block.items():
        if len(items) / len(found) < PRESENT_SHARE:
            continue
        out[key] = {
            "tokens": median_high(int(i.get("tokens") or 0) for i in items),
            "revision": Counter(str(i.get("revision")) for i in items).most_common(1)[0][0],
            "scope": items[0].get("scope"), "kind": items[0].get("kind"),
        }
    return out


async def _labels(db: AsyncSession, keys: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], str]:
    memory_ids = [k[1] for k in keys if k[0] == "memory"]
    names: dict[str, str] = {}
    if memory_ids:
        rows = (await db.execute(text(
            "SELECT CAST(id AS text) AS id, COALESCE(NULLIF(name, ''), summary) AS label FROM memories WHERE CAST(id AS text) = ANY(:ids)"
        ), {"ids": memory_ids})).all()
        names = {r.id: str(r.label) for r in rows if r.label}
    return {k: (names.get(k[1]) or k[1])[:80] if k[0] == "memory" else k[1] for k in keys}


async def block_changes(db: AsyncSession, before_rows: list[FirstTurn], after_rows: list[FirstTurn],
                        revisions: list[Marker]) -> list[BlockChange]:
    before, after = await _deliveries(db, before_rows), await _deliveries(db, after_rows)
    projects = {project for project, _ in after}
    same_project = [d for d in before if d[0] in projects]
    old, new = _block_sets(same_project or before), _block_sets(after)  # project blocks differ by project: compare like with like
    changes: list[tuple[str, tuple[str, str, str], int, int]] = []
    for key in old.keys() | new.keys():
        a, b = old.get(key), new.get(key)
        if a is None and b is not None:
            changes.append(("added", key, 0, b["tokens"]))
        elif b is None and a is not None:
            changes.append(("removed", key, a["tokens"], 0))
        elif a is not None and b is not None:
            if b["tokens"] != a["tokens"]:
                changes.append(("grown" if b["tokens"] > a["tokens"] else "shrunk", key, a["tokens"], b["tokens"]))
            elif b["revision"] != a["revision"]:
                changes.append(("revised", key, a["tokens"], b["tokens"]))
    changes.sort(key=lambda c: -abs(c[3] - c[2]))
    changes = changes[:BLOCK_LIMIT]
    labels = await _labels(db, [c[1] for c in changes])
    newest: dict[str, Marker] = {}
    for marker in revisions:
        if marker.kind in ("memory", "prompt"):
            newest[marker.ref] = marker  # revisions come oldest first
    out = []
    for change, key, tokens_before, tokens_after in changes:
        marker = newest.get(key[1])
        if marker is not None and labels[key] == key[1]:
            labels[key] = marker.label[:80]  # the memory row is gone (deleted): the revision still has its name
        writer = None
        if marker is not None:
            writer = {"at": marker.at.isoformat(), **{k: marker.detail.get(k) for k in ("action", "writer_kind", "writer_session", "changed_by")}}
        side = new.get(key) or old.get(key) or {}
        out.append(BlockChange(change=change, block=key[2], kind=side.get("kind"), scope=side.get("scope"), label=labels[key],
                               tokens_before=tokens_before, tokens_after=tokens_after, delta=tokens_after - tokens_before, writer=writer))
    return out


def _dominant_model(rows: list[FirstTurn]) -> str | None:
    known = [r.model for r in rows if r.model]
    return Counter(known).most_common(1)[0][0] if known else None


def _cause(*, delta: int | None, ours: int | None, harness: int | None, brief: int | None, version_changed: bool,
           fp_changed: bool, knob_changed: bool, model_changed: bool) -> str:
    """The part that moved most, or "unknown" when the known parts cannot account for the move.

    A part that is not known (a harness with no split, a remote host) is not zero: when the parts we do know cover less
    than half of the move, or the unexplained rest is the largest, the cause is "unknown" unless a model change explains
    the rest. Two parts within a factor of two of each other (ties included) are "mixed". A harness move with a version
    and a knob, or another model and a version or fingerprint, changed at once is "unknown". "none": nothing moved."""
    if delta is None:
        return "unknown"
    if delta == 0:
        return "none"
    known = {k: v for k, v in (("ours", ours), ("harness", harness), ("brief", brief)) if v is not None}
    if len(known) == 3:
        rest = abs(delta - sum(known.values()))
        if rest > max(abs(v) for v in known.values()):
            return "model" if model_changed else "unknown"
    if sum(abs(v) for v in known.values()) * 2 < abs(delta):
        return "unknown"
    ranked = sorted(known, key=lambda k: -abs(known[k]))
    top = ranked[0]
    if len(ranked) > 1 and abs(known[ranked[1]]) * 2 > abs(known[top]):
        return "mixed"  # two parts moved about alike: size alone does not pick one
    if top in ("ours", "brief"):
        return top
    if model_changed and (version_changed or fp_changed):
        return "unknown"  # another model and a new version or fingerprint at once: the windows are not alike
    if version_changed:
        return "unknown" if knob_changed else "harness_version"  # a knob and a version at once: not told apart
    if fp_changed:
        return "config"
    return "model" if model_changed else "harness"


def _summary(w: Why, names: list[str]) -> str:
    who = f"{w.harness} {w.role}"
    if w.before is None or w.after is None or w.before.total is None or w.after.total is None:
        return f"{who}: not enough measured starts on both sides to say what moved."
    lead = f"{who}: {_k(w.before.total)} -> {_k(w.after.total)} ({_signed(w.delta)}, {w.pct:+.0f}%)"
    at = f" at {w.at:%Y-%m-%d %H:%MZ}" if w.at else ""
    bits = []
    if w.config_fp.get("from") != w.config_fp.get("to"):
        bits.append("request shape changed")
    if w.version.get("from") != w.version.get("to"):
        bits.append(f"{w.harness} {w.version.get('from')} -> {w.version.get('to')}")
    elif w.version.get("to"):
        bits.append(f"{w.harness} {w.version['to']} unchanged")
    if w.model.get("from") != w.model.get("to"):
        bits.append(f"model {w.model.get('from')} -> {w.model.get('to')}")
    split = f"harness {_signed(w.parts.get('harness'))}, ours {_signed(w.parts.get('ours'))}, brief {_signed(w.parts.get('brief'))}"
    knob = f" Knob: {', '.join(names)}." if names else ""
    together = f" Changed together: {', '.join(CHANGED_WORDS.get(c, c) for c in w.changed)}." if len(w.changed) > 1 and w.cause in ("mixed", "unknown") else ""
    return f"{lead}{at}: cause {w.cause}. {'; '.join(bits)}. {split}.{together}{knob}"


def _step_cell(rows: list[FirstTurn], at: datetime) -> str | None:
    """The cell a step belongs to: a start exactly at `at` (a boundary step is its first start), else the cell with the
    most starts within a day of it."""
    exact = [r.cell for r in rows if r.at == at]
    near = [r.cell for r in rows if abs(r.at - at) <= timedelta(days=1)]
    pick = exact or near
    return Counter(pick).most_common(1)[0][0] if pick else None


async def explain(db: AsyncSession, rows: list[FirstTurn], harness: str, role: str, at: datetime | None, *,
                  policy: Policy, now: datetime, kind: str, model: str | None, cell: str | None = None,
                  found: Found | None = None) -> Why:
    """Compare the 7 days before `at` with `at` onward, for rows of one cell (restricted to one model if given).

    With `found` (a step from the step finder) the two sides are the step's own starts, so a step reads the same here, in
    the Trend and in the Cell view. A group role ("lane") spans several roles, so the move is read in one role of it:
    `cell`, else the role of the step at `at`. Before and after then hold the same role and the delta matches the step's."""
    if at is None:
        return Why(harness=harness, role=role, at=None, kind=kind, cause="none", before=None, after=None, delta=None, pct=None,
                   summary=f"{harness} {role}: no measured starts in the window.")
    if found is not None:
        cell, model = found.step.role, found.step.model
    if role in ROLE_GROUPS:
        cell = cell or _step_cell([r for r in rows if model is None or r.model == model], at)
        if cell is not None:
            rows = [r for r in rows if r.cell == cell]
    same_model = [r for r in rows if model is None or r.model == model]
    before_rows = found.before_rows if found is not None else [r for r in same_model if at - timedelta(days=BASELINE_DAYS) <= r.at < at]
    after_rows = found.after_rows if found is not None else [r for r in same_model if r.at >= at]
    before, after = window(before_rows), window(after_rows)
    delta = _diff(before.total, after.total)
    pct = None if delta is None or not before.total else delta / before.total * 100
    parts = {"harness": _diff(before.harness, after.harness), "ours": _diff(before.ours, after.ours), "brief": _diff(before.brief, after.brief)}
    known = [parts[k] for k in ("harness", "ours", "brief")]
    parts["other"] = None if delta is None or any(v is None for v in known) else delta - sum(v for v in known if v is not None)

    lo = before.end if before.end is not None else at - timedelta(days=1)
    hi = after.start if after.start is not None else min(now, at + timedelta(hours=1))
    lo, hi = min(lo, at), max(hi, at)
    seen = [m for m in await view_markers(db, lo, hi, harness=harness)
             if m.kind != "config" or (in_cell(cell or role, m.launch_mode, m.role) and (model is None or m.detail.get("model") == model))]
    changed_knobs = await knob_markers(policy.knobs_for(harness, cell or role), lo, hi)
    revisions = [m for m in seen if m.kind in ("memory", "prompt")]

    # One side's version, fingerprint and model are what its starts mostly had, so these lines and the part changes
    # above describe the same two sets of starts.
    if found is not None and after.start and after.end:
        # every model in the same cell over each side's span: the step's own sides hold one model, a model change shows here
        model_from = _dominant_model([r for r in rows if at - timedelta(days=BASELINE_DAYS) <= r.at < at])
        model_to = _dominant_model([r for r in rows if after.start <= r.at <= after.end])
    else:
        model_from = _dominant_model([r for r in rows if at - timedelta(days=BASELINE_DAYS) <= r.at < at])
        model_to = _dominant_model([r for r in rows if r.at >= at])
    version = {"from": before.version, "to": after.version}
    config_fp = {"from": before.config_fp, "to": after.config_fp}
    fp_changed = config_fp["from"] != config_fp["to"]
    # A knob file's commit is only a cause when what the harness loads changed with it (the fingerprint); otherwise it
    # stays on the timeline as a marker.
    knobs = changed_knobs if fp_changed else []
    result = Why(
        harness=harness, role=role, at=at, kind=kind, cause="none", before=before, after=after, delta=delta, pct=pct, parts=parts,
        version=version, config_fp=config_fp, model={"from": model_from, "to": model_to}, knobs=knobs,
        markers=[*seen, *changed_knobs],
        blocks=await block_changes(db, before_rows, after_rows, revisions),
    )
    result.markers.sort(key=lambda m: m.at)
    result.cause = _cause(
        delta=delta, ours=parts["ours"], harness=parts["harness"], brief=parts["brief"],
        version_changed=version["from"] != version["to"], fp_changed=fp_changed, knob_changed=bool(knobs),
        model_changed=model_from != model_to,
    )
    result.changed = [name for name, on in (("model", model_from != model_to), ("config_fp", fp_changed), ("version", version["from"] != version["to"])) if on]
    result.summary = _summary(result, sorted({k.label for k in knobs}))
    return result


async def why(db: AsyncSession, harness: str, role: str, *, at: datetime | None = None, now: datetime | None = None,
              policy: Policy | None = None, recent: bool = False) -> Why:
    """Explain a cell. With `at`, the move at that time; with `recent`, the last 24 h against the week before (the
    window a budget card is about); otherwise the newest step, else the last 24 h against the week before."""
    now = now or datetime.now(UTC)
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=UTC)  # a time typed without a zone is UTC, as every time here is printed
    policy = policy or await load_policy(db)
    rows = cell_rows(await load_first_turns(db, since=now - timedelta(days=LOOKBACK_DAYS), harness=harness), harness, role)
    if at is not None:
        # A time that names a step (to the minute, as the Trend prints it) is that step, with the same two sides.
        if policy.jump_pct is not None:
            named = [f for f in find_step_rows(rows, policy.jump_pct) if abs((f.step.at - at).total_seconds()) < STEP_MATCH_S]
            if named:
                found = min(named, key=lambda f: abs((f.step.at - at).total_seconds()))
                return await explain(db, rows, harness, role, found.step.at, policy=policy, now=now, kind=found.step.kind,
                                     model=found.step.model, cell=found.step.role, found=found)
        model = _dominant_model([r for r in rows if at - timedelta(days=BASELINE_DAYS) <= r.at < at]) or _dominant_model(rows)
        return await explain(db, rows, harness, role, at, policy=policy, now=now, kind="at", model=model)
    steps = [] if recent or policy.jump_pct is None else find_step_rows(rows, policy.jump_pct)
    if steps:
        found = steps[-1]
        return await explain(db, rows, harness, role, found.step.at, policy=policy, now=now, kind=found.step.kind, model=found.step.model,
                             cell=found.step.role, found=found)
    return await explain(db, rows, harness, role, now - timedelta(hours=RECENT_HOURS) if rows else None, policy=policy, now=now,
                         kind="recent", model=_dominant_model([r for r in rows if r.at >= now - timedelta(hours=RECENT_HOURS)]))


async def steps_with_markers(db: AsyncSession, harness: str, role: str, *, days: int = DEFAULT_STEPS_DAYS, now: datetime | None = None,
                             policy: Policy | None = None) -> list[Step]:
    """The cell's steps (every move of at least jump_pct) with the markers between the last start before and the first after."""
    now = now or datetime.now(UTC)
    policy = policy or await load_policy(db)
    if policy.jump_pct is None:
        return []
    edge = now - timedelta(days=days)
    # Rows go back as far as the Trend loads them, so a step near the range's start has its whole week before it.
    rows = cell_rows(await load_first_turns(db, since=edge - timedelta(days=days + 1), until=now, harness=harness), harness, role)
    steps = [s for s in find_steps(rows, policy.jump_pct) if s.at >= edge]
    for step in steps:
        lo = step.before.end or step.at - timedelta(days=1)
        hi = step.after.start or step.at
        lo, hi = min(lo, step.at), max(hi, step.at)
        found = [m for m in await view_markers(db, lo, hi, harness=harness)
                 if m.kind != "config" or (in_cell(step.role, m.launch_mode, m.role) and m.detail.get("model") == step.model)]
        step.markers = sorted([*found, *await knob_markers(policy.knobs_for(harness, step.role), lo, hi)], key=lambda m: m.at)
    return steps
