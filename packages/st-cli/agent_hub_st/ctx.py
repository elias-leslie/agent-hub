"""st ctx: what Agent Hub and the harnesses put in an agent's first turn, why it moved, and who changed it.

Reads the context-observability API (Cost matrix, trend, cell, why, markers, budgets); the review queue commands are in
ctx_changes. Every command prints at most 15 lines; ``--json`` prints the (filtered) API response unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import typer
from st_sdk.output import output_json
from st_sdk.usage import usage

from . import ctx_changes
from ._api_paths import (
    CONTEXT_OBS_BUDGET_STATE_PATH,
    CONTEXT_OBS_BUDGETS_PATH,
    CONTEXT_OBS_CELL_PATH,
    CONTEXT_OBS_JUMP_PATH,
    CONTEXT_OBS_MARKERS_PATH,
    CONTEXT_OBS_MATRIX_PATH,
    CONTEXT_OBS_TREND_PATH,
    CONTEXT_OBS_WHY_PATH,
)
from .ctx_format import ON_DEMAND, TASKS, TOOL, UNKNOWN, day, emit, fp, obj, pct, rows, short, table, tok, when
from .memory_api import agent_hub_request

app = typer.Typer(help="Context cost: what lands in an agent's first turn, why it moved, and the changes to review")
Harness = Annotated[str, typer.Argument(help="claude, codex, pi or agent_hub")]
Role = Annotated[str, typer.Argument(help="A Cost-matrix role, or lane (every launched role but the coordinator)")]
AsJson = Annotated[bool, typer.Option("--json", help="Print the API response as JSON.")]


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    return agent_hub_request("GET", path, params=params, tool_name=TOOL)


def _cell_match(cell: str, wanted: str | None) -> bool:
    return not wanted or cell == wanted or cell.startswith(f"{wanted}:")


def _flag(value: Any) -> str:
    return {"warn": "OVER-BUDGET", "jump": "JUMP"}.get(str(value), str(value)) if value else ""


@app.command("cost")
@usage(surface="st.ctx.cost", cmd="st ctx cost [-H HARNESS] [-r ROLE] [--days N]",
       when="first-turn tokens per harness and role: median, change, harness/ours/brief split, budget flags",
       task_types=TASKS, on_demand=ON_DEMAND)
def cost(
    harness: Annotated[str | None, typer.Option("-H", "--harness", help="One harness; agent_hub shows Agent Hub's own agents.")] = None,
    role: Annotated[str | None, typer.Option("-r", "--role", help="One role (coordinator, implementation, subagent...).")] = None,
    days: Annotated[int, typer.Option("--days", min=1, max=90)] = 14,
    limit: Annotated[int, typer.Option("--limit", min=1, max=13, help="Rows shown; flagged ones first.")] = 12,
    as_json: AsJson = False,
) -> None:
    """The Cost matrix: median first turn per harness and role, flagged cells first."""
    payload = obj(_get(CONTEXT_OBS_MATRIX_PATH, {"days": days}))
    cells = [c for c in rows(payload.get("cells"))
             if (harness == c.get("harness") if harness else c.get("harness") != "agent_hub")
             and _cell_match(str(c.get("cell")), role)]
    if as_json:
        output_json({**payload, "cells": cells})
        return
    cells.sort(key=lambda c: (not c.get("flag"), -int(c.get("n") or 0)))
    versions = ", ".join(f"{h.get('harness')} {h.get('version') or UNKNOWN}" for h in rows(payload.get("harnesses"))
                         if h.get("harness") != "agent_hub")
    since = f" data from {day(payload.get('coverage_from'))}" if payload.get("coverage_from") else ""
    lines = [f"COST {days}d jump>={payload.get('jump_pct') or UNKNOWN}%{since} | {versions or UNKNOWN}"]
    if not cells:
        lines.append("no starts match")
    body = [[f"{c.get('harness')}/{c.get('cell')}", f"n={c.get('n')}", tok(c.get("total")), pct(c.get("delta_pct")),
             f"h {tok(c.get('harness_tokens'))} o {tok(c.get('ours'))} b {tok(c.get('brief'))}",
             f"warn {tok(c.get('warn_tokens'))}" + (f" {_flag(c.get('flag'))}" if c.get("flag") else "")] for c in cells[:limit]]
    lines += table(body)
    if len(cells) > limit:
        lines.append(f"+{len(cells) - limit} more cells (-H, -r narrow)")
    emit(lines)


@app.command("trend")
@usage(surface="st.ctx.trend", cmd="st ctx trend HARNESS ROLE [--days N]",
       when="one cell over time: median, change, steps with their cause, versions seen, daily medians",
       task_types=TASKS, on_demand=ON_DEMAND)
def trend(harness: Harness, role: Role, days: Annotated[int, typer.Option("--days", min=1, max=90)] = 30, as_json: AsJson = False) -> None:
    """One cell over time with the steps the step finder flagged."""
    payload = obj(_get(CONTEXT_OBS_TREND_PATH, {"harness": harness, "role": role, "days": days}))
    if as_json:
        output_json(payload)
        return
    head = obj(payload.get("headline"))
    prev = f" (was {tok(head.get('prev_total'))}, {pct(head.get('delta_pct'))})" if head.get("prev_total") else ""
    lines = [f"TREND {harness}/{role} {days}d n={head.get('n', 0)} median {tok(head.get('total'))}{prev} warn {tok(payload.get('warn_tokens'))}"
             f" from {day(payload.get('coverage_from'))}",
             f"  harness {tok(head.get('harness_tokens'))}  ours {tok(head.get('ours'))}  brief {tok(head.get('brief'))}"]
    steps = sorted(rows(payload.get("steps")), key=lambda s: str(s.get("at")), reverse=True)
    for step in steps[:5]:
        parts = obj(step.get("parts"))
        lines.append(f"  {when(step.get('at'))} {tok(step.get('before_total'))}->{tok(step.get('after_total'))} {pct(step.get('pct'))} "
                     f"cause={step.get('cause') or UNKNOWN} h {tok(parts.get('harness'), sign=True)} o {tok(parts.get('ours'), sign=True)}")
    if not steps:
        lines.append("  no steps")
    elif len(steps) > 5:
        lines.append(f"  +{len(steps) - 5} older steps")
    versions = " ".join(f"{v.get('version')}({day(v.get('first_at'))})" for v in rows(payload.get("versions"))[-4:])
    lines.append(f"  versions {versions or UNKNOWN}")
    recent = rows(payload.get("daily"))[-6:]
    lines.append("  daily " + (" ".join(f"{day(d.get('day'))}:{tok(d.get('total'))}" for d in recent) or UNKNOWN))
    emit(lines)


@app.command("cell")
@usage(surface="st.ctx.cell", cmd="st ctx cell HARNESS ROLE",
       when="one cell's latest start: parts, biggest delivered blocks with last writer, growth, newest move",
       task_types=TASKS, on_demand=ON_DEMAND)
def cell(harness: Harness, role: Role, as_json: AsJson = False) -> None:
    """The latest start of a cell: where its tokens are, block by block."""
    payload = obj(_get(CONTEXT_OBS_CELL_PATH, {"harness": harness, "role": role}))
    if as_json:
        output_json(payload)
        return
    latest = obj(payload.get("latest"))
    if not latest:
        emit([f"CELL {harness}/{role}: no measured start in {payload.get('lookback_days', 30)}d"])
        return
    parts = obj(payload.get("parts"))

    def part(name: str) -> str:
        value = obj(parts.get(name))
        return f"{name} {tok(value.get('tokens'))}" + ("" if value.get("method") in (None, "exact", "derived") else "~")

    names = [n for n in ("harness_core", "harness_tools", "our_listings", "ah_global", "ah_role", "ah_project") if n in parts]
    lines = [f"CELL {harness}/{role} {when(latest.get('at'))} {tok(latest.get('total'))} (h {tok(latest.get('harness_tokens'))} "
             f"o {tok(latest.get('ours'))} b {tok(latest.get('brief'))}) {latest.get('version') or UNKNOWN} {latest.get('model') or UNKNOWN} "
             f"cfg {fp(payload.get('config_fp'))}",
             "  " + ("  ".join(part(n) for n in names) or "parts not split yet") + "  (~ = ratio estimate)"]
    blocks = rows(payload.get("blocks"))
    lines.append(f"  blocks {len(blocks)}, {tok(payload.get('blocks_total'))} delivered:")
    for block in blocks[:5]:
        who = block.get("writer_session") or block.get("writer_kind")
        lines.append(f"    {tok(block.get('tokens')):>6} {short(block.get('label') or block.get('block_id'), 36)} {block.get('scope') or UNKNOWN}"
                     + (f" {when(block.get('writer_at'))} {block.get('writer_action') or ''} {short(who, 16)}" if block.get("writer_at") else ""))
    growth = obj(payload.get("growth"))
    if growth.get("measured"):
        lines.append(f"  growth peak median {tok(growth.get('median_peak'))} max {tok(growth.get('max_peak'))}; "
                     f"{growth.get('compacted')}/{growth.get('sessions')} sessions compacted")
    move = obj(payload.get("latest_move"))
    if move:
        lines.append(f"  last move {when(move.get('at'))} {tok(move.get('delta'), sign=True)} {pct(move.get('pct'))} cause={move.get('cause')}")
    state = obj(payload.get("state"))
    lines.append(f"  budget warn {tok(payload.get('budget_warn'))} jump {payload.get('budget_jump_pct') or UNKNOWN}%"
                 + (f" -> {_flag(state.get('reason'))}" if state.get("reason") else " ok"))
    emit(lines)


@app.command("why")
@usage(surface="st.ctx.why", cmd="st ctx why HARNESS ROLE [--at TIME]",
       when="why a cell moved: cause (ours, config, harness version, brief, model), parts delta, changed blocks with writer, knob",
       task_types=TASKS, on_demand=ON_DEMAND)
def why(
    harness: Harness, role: Role,
    at: Annotated[str | None, typer.Option("--at", help="Explain the move at this ISO time; default the newest step.")] = None,
    as_json: AsJson = False,
) -> None:
    """What moved a cell's first turn, biggest first."""
    payload = obj(_get(CONTEXT_OBS_WHY_PATH, {"harness": harness, "role": role, **({"at": at} if at else {})}))
    if as_json:
        output_json(payload)
        return
    before, after, parts = obj(payload.get("before")), obj(payload.get("after")), obj(payload.get("parts"))
    lines = [f"WHY {harness}/{role} cause={payload.get('cause') or UNKNOWN} {payload.get('kind') or ''} at {when(payload.get('at'))}"]
    if payload.get("summary"):
        lines.append("  " + short(payload["summary"], 200))
    if before or after:
        lines.append(f"  {tok(before.get('total'))} n={before.get('n', 0)} v{before.get('version') or UNKNOWN} cfg {fp(before.get('config_fp'))}"
                     f" -> {tok(after.get('total'))} n={after.get('n', 0)} v{after.get('version') or UNKNOWN} cfg {fp(after.get('config_fp'))}")
    lines.append("  parts " + "  ".join(f"{name} {tok(value, sign=True)}" for name, value in parts.items()))
    for knob in rows(payload.get("knobs"))[:2]:
        lines.append(f"  knob {knob.get('label')} {when(knob.get('at'))} {fp(knob.get('ref'))}")
    blocks = sorted(rows(payload.get("blocks")), key=lambda b: -abs(int(b.get("delta") or 0)))
    for block in blocks[:5]:
        writer = obj(block.get("writer"))
        who = writer.get("writer_session") or writer.get("session") or writer.get("writer_kind") or writer.get("kind")
        lines.append(f"  {block.get('change')} {tok(block.get('delta'), sign=True)} {short(block.get('label') or block.get('block'), 34)} "
                     f"{block.get('scope') or UNKNOWN}" + (f" by {short(who, 16)}" if who else ""))
    if len(blocks) > 5:
        lines.append(f"  +{len(blocks) - 5} smaller block changes")
    emit(lines)


@app.command("markers")
@usage(surface="st.ctx.markers", cmd="st ctx markers [-H HARNESS] [--days N] [--kind KIND]",
       when="what changed lately: memory and prompt revisions of delivered blocks, harness versions, configs, placements",
       task_types=TASKS, on_demand=ON_DEMAND)
def markers(
    harness: Annotated[str | None, typer.Option("-H", "--harness")] = None,
    days: Annotated[int, typer.Option("--days", min=1, max=90)] = 3,
    kind: Annotated[str | None, typer.Option("--kind", help="memory, prompt, harness_version, config, placement or knob")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=13, help="Newest N shown.")] = 12,
    as_json: AsJson = False,
) -> None:
    """Markers, oldest first, the newest N."""
    stop = datetime.now(UTC)
    found = rows(_get(CONTEXT_OBS_MARKERS_PATH, {"start": (stop - timedelta(days=days)).isoformat(), "end": stop.isoformat(),
                                                  **({"harness": harness} if harness else {})}))
    found = [m for m in found if not kind or m.get("kind") == kind]
    if as_json:
        output_json(found)
        return
    lines = [f"MARKERS {days}d {len(found)} found" + (f", newest {limit}" if len(found) > limit else "")]
    for marker in found[-limit:]:
        detail = obj(marker.get("detail"))
        who = detail.get("writer_session") or detail.get("writer_kind")
        extra = " ".join(str(x) for x in (detail.get("action"), tok(detail.get("tokens")) + "t" if detail.get("tokens") is not None else None) if x)
        lines.append(f"  {when(marker.get('at'))} {marker.get('kind')} {short(marker.get('label'), 38)} {extra}" + (f" by {short(who, 16)}" if who else ""))
    emit(lines)


budget_app = typer.Typer(help="Budget levels that raise the context alerts")
app.add_typer(budget_app, name="budget")


@budget_app.callback(invoke_without_command=True)
@usage(surface="st.ctx.budget", cmd="st ctx budget [set HARNESS ROLE TOKENS | jump PCT | rm HARNESS ROLE]",
       when="show warn levels and cells over them; set, jump and rm edit the levels that raise the Nightshift alert",
       task_types=TASKS, on_demand=ON_DEMAND)
def budget(ctx: typer.Context, as_json: AsJson = False) -> None:
    """Warn levels (harness or *, role or *) and the cells over budget."""
    if ctx.invoked_subcommand is not None:
        return
    levels = rows(_get(CONTEXT_OBS_BUDGETS_PATH))
    states = rows(_get(CONTEXT_OBS_BUDGET_STATE_PATH))
    if as_json:
        output_json({"budgets": levels, "state": states})
        return
    jump = next((r.get("jump_pct") for r in levels if r.get("harness") == "*" and r.get("role") == "*"), None)
    lines = [f"BUDGETS {len(levels)} levels, step alert at +{jump or UNKNOWN}%"]
    lines += table([[f"{r.get('harness')}/{r.get('role')}", f"warn {tok(r.get('warn_tokens'))}", short(r.get("note"), 50)] for r in levels[:8]], indent="  ")
    over = [s for s in states if s.get("reason")]
    measured = sum(1 for s in states if s.get("n_recent"))
    lines.append(f"  {len(over)} over, {measured} cells measured in 24h" + (":" if over else ""))
    for state in over[:4]:
        lines.append(f"  {state.get('harness')}/{state.get('cell')} {_flag(state.get('reason'))} {tok(state.get('recent'))} "
                     f"vs warn {tok(state.get('warn_tokens'))}, week before {tok(state.get('baseline'))} ({pct(state.get('pct'))})")
    emit(lines)


@budget_app.command("set")
def budget_set(
    harness: Annotated[str, typer.Argument(help="claude, codex, pi... or * for any")],
    role: Annotated[str, typer.Argument(help="A role, lane, or * for any")],
    tokens: Annotated[int, typer.Argument(min=1, help="Warn above this median first turn")],
    note: Annotated[str | None, typer.Option("--note")] = None,
) -> None:
    """Set the warn level of one (harness, role) cell."""
    row = obj(agent_hub_request("PUT", CONTEXT_OBS_BUDGETS_PATH, json={"harness": harness, "role": role, "warn_tokens": tokens, "note": note},
                                tool_name=TOOL))
    print(f"budget {row.get('harness', harness)}/{row.get('role', role)} warn {tok(row.get('warn_tokens', tokens))}")


@budget_app.command("jump")
def budget_jump(pct_value: Annotated[int, typer.Argument(min=1, max=1000, metavar="PCT", help="Step alert threshold, percent")]) -> None:
    """Set the one global step threshold."""
    row = obj(agent_hub_request("PUT", CONTEXT_OBS_JUMP_PATH, json={"jump_pct": pct_value}, tool_name=TOOL))
    print(f"step alert at +{row.get('jump_pct', pct_value)}%")


@budget_app.command("rm")
def budget_rm(harness: Annotated[str, typer.Argument()], role: Annotated[str, typer.Argument()]) -> None:
    """Remove a cell's own level so the next most specific one applies."""
    agent_hub_request("DELETE", CONTEXT_OBS_BUDGETS_PATH, params={"harness": harness, "role": role}, tool_name=TOOL)
    print(f"budget {harness}/{role} removed")


ctx_changes.register(app)
