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
from .steps import BASELINE_DAYS, Step, Window, cell_rows, find_steps, in_cell, window

LOOKBACK_DAYS = 30
RECENT_HOURS = 24
BLOCK_LIMIT = 15
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
    cause: str  # ours | config | harness_version | harness | model | brief | none
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


def _cause(*, ours: int | None, harness: int | None, version_changed: bool, fp_changed: bool, knob_changed: bool,
           model_changed: bool, brief: int | None) -> str:
    moves = {"ours": abs(ours or 0), "harness": abs(harness or 0), "brief": abs(brief or 0)}
    top = max(moves, key=lambda k: moves[k])
    if moves[top] == 0:
        return "none"
    if top == "ours":
        return "ours"
    if top == "brief":
        return "brief"
    if knob_changed or (fp_changed and not version_changed):
        return "config"
    if version_changed:
        return "harness_version"
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
        bits.append(f"config_fp {str(w.config_fp.get('from'))[:8]} -> {str(w.config_fp.get('to'))[:8]}")
    if w.version.get("from") != w.version.get("to"):
        bits.append(f"{w.harness} {w.version.get('from')} -> {w.version.get('to')}")
    elif w.version.get("to"):
        bits.append(f"{w.harness} {w.version['to']} unchanged")
    if w.model.get("from") != w.model.get("to"):
        bits.append(f"model {w.model.get('from')} -> {w.model.get('to')}")
    split = f"harness {_signed(w.parts.get('harness'))}, ours {_signed(w.parts.get('ours'))}, brief {_signed(w.parts.get('brief'))}"
    knob = f" Knob: {', '.join(names)}." if names else ""
    return f"{lead}{at}: cause {w.cause}. {'; '.join(bits)}. {split}.{knob}"


async def explain(db: AsyncSession, rows: list[FirstTurn], harness: str, role: str, at: datetime | None, *,
                  policy: Policy, now: datetime, kind: str, model: str | None) -> Why:
    """Compare the 7 days before `at` with `at` onward, for rows of one cell (restricted to one model if given)."""
    if at is None:
        return Why(harness=harness, role=role, at=None, kind=kind, cause="none", before=None, after=None, delta=None, pct=None,
                   summary=f"{harness} {role}: no measured starts in the window.")
    same_model = [r for r in rows if model is None or r.model == model]
    before_rows = [r for r in same_model if at - timedelta(days=BASELINE_DAYS) <= r.at < at]
    after_rows = [r for r in same_model if r.at >= at]
    before, after = window(before_rows), window(after_rows)
    delta = _diff(before.total, after.total)
    pct = None if delta is None or not before.total else delta / before.total * 100
    parts = {"harness": _diff(before.harness, after.harness), "ours": _diff(before.ours, after.ours), "brief": _diff(before.brief, after.brief)}
    known = [parts[k] for k in ("harness", "ours", "brief")]
    parts["other"] = None if delta is None or any(v is None for v in known) else delta - sum(v for v in known if v is not None)

    lo = before.end if before.end is not None else at - timedelta(days=1)
    hi = after.start if after.start is not None else min(now, at + timedelta(hours=1))
    lo, hi = min(lo, at), max(hi, at)
    found = [m for m in await view_markers(db, lo, hi, harness=harness)
             if m.kind != "config" or (in_cell(role, m.launch_mode, m.role) and (model is None or m.detail.get("model") == model))]
    knobs = await knob_markers(policy.knobs_for(harness, role), lo, hi)
    revisions = [m for m in found if m.kind in ("memory", "prompt")]

    # The state at the step is read from one role (a "lane" query spans several roles with their own fingerprints).
    near = [r for r in same_model if abs(r.at - at) <= timedelta(days=1)]
    own = Counter(r.cell for r in near).most_common(1)[0][0] if near else None
    last_before = next((r for r in reversed(before_rows) if r.cell == own), None)
    first_after = next((r for r in after_rows if r.cell == own), None)
    model_from = _dominant_model([r for r in rows if at - timedelta(days=BASELINE_DAYS) <= r.at < at])
    model_to = _dominant_model([r for r in rows if r.at >= at])
    result = Why(
        harness=harness, role=role, at=at, kind=kind, cause="none", before=before, after=after, delta=delta, pct=pct, parts=parts,
        version={"from": last_before.version if last_before else before.version, "to": first_after.version if first_after else after.version},
        config_fp={"from": last_before.config_fp if last_before else before.config_fp,
                   "to": first_after.config_fp if first_after else after.config_fp},
        model={"from": model_from, "to": model_to}, knobs=knobs,
        markers=[*found, *knobs],
        blocks=await block_changes(db, before_rows, after_rows, revisions),
    )
    result.markers.sort(key=lambda m: m.at)
    result.cause = _cause(
        ours=parts["ours"], harness=parts["harness"], brief=parts["brief"],
        version_changed=result.version["from"] != result.version["to"],
        fp_changed=result.config_fp["from"] != result.config_fp["to"], knob_changed=bool(knobs), model_changed=model_from != model_to,
    )
    names = sorted({k.label for k in knobs}) if result.cause == "config" else []
    result.summary = _summary(result, names)
    return result


async def why(db: AsyncSession, harness: str, role: str, *, at: datetime | None = None, now: datetime | None = None,
              policy: Policy | None = None) -> Why:
    """Explain a cell. With `at`, the move at that time; without it, the newest step, else the last 24 h against the week before."""
    now = now or datetime.now(UTC)
    policy = policy or await load_policy(db)
    rows = cell_rows(await load_first_turns(db, since=now - timedelta(days=LOOKBACK_DAYS), harness=harness), harness, role)
    if at is not None:
        model = _dominant_model([r for r in rows if at - timedelta(days=BASELINE_DAYS) <= r.at < at]) or _dominant_model(rows)
        return await explain(db, rows, harness, role, at, policy=policy, now=now, kind="at", model=model)
    steps = find_steps(rows, policy.jump_pct) if policy.jump_pct is not None else []
    if steps:
        step = steps[-1]
        return await explain(db, rows, harness, role, step.at, policy=policy, now=now, kind=step.kind, model=step.model)
    return await explain(db, rows, harness, role, now - timedelta(hours=RECENT_HOURS) if rows else None, policy=policy, now=now,
                         kind="recent", model=_dominant_model([r for r in rows if r.at >= now - timedelta(hours=RECENT_HOURS)]))


async def steps_with_markers(db: AsyncSession, harness: str, role: str, *, days: int = LOOKBACK_DAYS, now: datetime | None = None,
                             policy: Policy | None = None) -> list[Step]:
    """The cell's steps (every move of at least jump_pct) with the markers between the last start before and the first after."""
    now = now or datetime.now(UTC)
    policy = policy or await load_policy(db)
    if policy.jump_pct is None:
        return []
    rows = cell_rows(await load_first_turns(db, since=now - timedelta(days=days), harness=harness), harness, role)
    steps = find_steps(rows, policy.jump_pct)
    for step in steps:
        lo = step.before.end or step.at - timedelta(days=1)
        hi = step.after.start or step.at
        lo, hi = min(lo, step.at), max(hi, step.at)
        found = [m for m in await view_markers(db, lo, hi, harness=harness)
                 if m.kind != "config" or (in_cell(role, m.launch_mode, m.role) and m.detail.get("model") == step.model)]
        step.markers = sorted([*found, *await knob_markers(policy.knobs_for(harness, role), lo, hi)], key=lambda m: m.at)
    return steps
