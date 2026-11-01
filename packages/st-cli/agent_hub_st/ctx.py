"""st ctx: what Agent Hub and the harnesses put in an agent's first turn, why it moved, and who changed it.

Reads the context-observability API (Cost matrix, trend, cell, why, markers, budgets); the review queue commands are in
ctx_changes. Every command prints at most 15 lines; ``--json`` prints the (filtered) API response unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import typer
from st_sdk.output import output_error, output_json
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
from .ctx_format import MAX_LINES, ON_DEMAND, TASKS, TOOL, UNKNOWN, day, emit, fp, obj, pct, rows, short, table, tok, when
from .ctx_marker import marker_line
from .memory_api import agent_hub_request

app = typer.Typer(help="Context cost: what lands in an agent's first turn, why it moved, and the changes to review")
HARNESSES = ("claude", "codex", "pi", "agent_hub")
Harness = Annotated[str, typer.Argument(metavar="HARNESS", help="claude, codex, pi or agent_hub")]
Role = Annotated[str, typer.Argument(metavar="ROLE", help="A role from st ctx cost, or lane (every launched role but the coordinator)")]
AsJson = Annotated[bool, typer.Option("--json", help="Print the API response as JSON.")]


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    return agent_hub_request("GET", path, params=params, tool_name=TOOL)


def _harness(value: str | None) -> str | None:
    """A harness the cost matrix knows; anything else is a typo, not an empty answer."""
    if value is not None and value not in HARNESSES:
        raise typer.BadParameter(f"{value!r} is not a harness; use {', '.join(HARNESSES)}", param_hint="HARNESS")
    return value


def _known_cell(harness: str, role: str) -> bool:
    """Whether the cost matrix (up to 90 days) has this cell; lane is every launched role, so it is always known."""
    if role == "lane":
        return True
    payload = obj(_get(CONTEXT_OBS_MATRIX_PATH, {"days": 90}))
    return any(c.get("harness") == harness and c.get("cell") == role for c in rows(payload.get("cells")))


def _unknown_cell(harness: str, role: str) -> None:
    """Stop with an error when an empty answer is really a role the matrix has never seen (a typo)."""
    if not _known_cell(harness, role):
        output_error(f"No {harness} cell named {role!r} in the last 90 days; the roles are in st ctx cost -H {harness}")
        raise typer.Exit(1)


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
    days: Annotated[int, typer.Option("--days", min=1, max=90, help="Compare the last N days with the N days before.")] = 14,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Rows shown, flagged first. A text answer stops at 15 lines; --json always returns every cell.")] = 12,
    as_json: AsJson = False,
) -> None:
    """The Cost matrix: median first turn per harness and role, flagged cells first."""
    _harness(harness)
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
    jump = payload.get("jump_pct") or UNKNOWN
    since = f"measured from {day(payload.get('coverage_from'))}" if payload.get("coverage_from") else ""
    launched = f", launched roles from {day(payload.get('launched_from'))}" if payload.get("launched_from") else ""
    lines = [f"COST last {days}d against the {days}d before | latest {versions or UNKNOWN} | {since}{launched}",
             f"  flagged: median up {jump}% or more (5+ starts each side), or over warn. harness = its own prompt and tools, "
             f"ours = what Agent Hub adds, brief = the task. {UNKNOWN} = not known or nothing before to compare"]
    if not cells:
        lines.append("no starts match")
    held = [c for c in cells if c.get("flag_held")]
    fixed = len(lines) + (1 if len(cells) > 1 else 0) + (1 if held else 0)
    shown = max(1, min(limit, MAX_LINES - fixed))
    body = [[f"{c.get('harness')}/{c.get('cell')}", f"n={c.get('n')}", tok(c.get("total")), pct(c.get("delta_pct")),
             f"harness {tok(c.get('harness_tokens'))} ours {tok(c.get('ours'))} brief {tok(c.get('brief'))}",
             f"warn {tok(c.get('warn_tokens'))}" + (f" {_flag(c.get('flag'))}" if c.get("flag") else "")] for c in cells[:shown]]
    lines += table(body)
    if len(cells) > shown:
        lines.append(f"+{len(cells) - shown} more cells (-H, -r narrow; --json lists all)")
    if held:
        lines.append(f"not flagged: {held[0].get('harness')}/{held[0].get('cell')} {short(held[0].get('flag_held'), 90)}"
                     + (f" (+{len(held) - 1} like it)" if len(held) > 1 else ""))
    emit(lines)


@app.command("trend")
@usage(surface="st.ctx.trend", cmd="st ctx trend HARNESS ROLE [--days N]",
       when="one cell over time: median, change, steps with their cause, versions seen, daily medians",
       task_types=TASKS, on_demand=ON_DEMAND)
def trend(harness: Harness, role: Role, days: Annotated[int, typer.Option("--days", min=1, max=90)] = 30, as_json: AsJson = False) -> None:
    """One cell over time with the steps the step finder flagged."""
    _harness(harness)
    payload = obj(_get(CONTEXT_OBS_TREND_PATH, {"harness": harness, "role": role, "days": days}))
    if not payload.get("daily") and not as_json:
        _unknown_cell(harness, role)
    if as_json:
        output_json(payload)
        return
    head = obj(payload.get("headline"))
    prev = f" (was {tok(head.get('prev_total'))}, {pct(head.get('delta_pct'))})" if head.get("prev_total") else ""
    lines = [f"TREND {harness}/{role} last {days}d, {head.get('n', 0)} starts, median {tok(head.get('total'))}{prev}, warn {tok(payload.get('warn_tokens'))}"
             f", measured from {day(payload.get('coverage_from'))}",
             f"  harness {tok(head.get('harness_tokens'))}  ours {tok(head.get('ours'))}  brief {tok(head.get('brief'))}"]
    models = rows(payload.get("models"))
    if len(models) > 1:
        lines.append("  mixes models: " + ", ".join(f"{str(m.get('model')).removeprefix('claude-')} {m.get('n')}" for m in models[:3]))
    steps = sorted(rows(payload.get("steps")), key=lambda s: str(s.get("at")), reverse=True)
    for step in steps[:4]:
        parts = obj(step.get("parts"))
        lines.append(f"  step {when(step.get('at'))} {tok(step.get('before_total'))}->{tok(step.get('after_total'))} {pct(step.get('pct'))} "
                     f"cause={step.get('cause') or UNKNOWN} (harness {tok(parts.get('harness'), sign=True)}, ours {tok(parts.get('ours'), sign=True)})")
    if not steps:
        jump = payload.get("jump_pct")
        lines.append(f"  no step: a lasting move of {jump}% or more with 5+ starts each side" if jump else "  no step finder: no jump level is set")
    elif len(steps) > 4:
        lines.append(f"  +{len(steps) - 4} older steps")
    for dip in rows(payload.get("dips"))[:2]:
        lines.append(f"  not a step: {day(dip.get('day'))} {tok(dip.get('before_total'))}->{tok(dip.get('total'))} {pct(dip.get('pct'))}: "
                     f"{short(dip.get('reason'), 150)}")
    versions = " ".join(f"{v.get('version')}({day(v.get('first_at'))})" for v in rows(payload.get("versions"))[-4:])
    lines.append(f"  versions (first seen) {versions or UNKNOWN}")
    recent = rows(payload.get("daily"))[-6:]
    lines.append("  daily medians " + (" ".join(f"{day(d.get('day'))}:{tok(d.get('total'))}" for d in recent) or UNKNOWN))
    emit(lines)


_PARTS = {"harness_core": "core prompt", "harness_tools": "tools", "our_listings": "our listings", "ah_global": "global",
          "ah_role": "role", "ah_project": "project"}


@app.command("cell")
@usage(surface="st.ctx.cell", cmd="st ctx cell HARNESS ROLE",
       when="one cell's latest start: parts, biggest delivered blocks with last writer, growth, newest move",
       task_types=TASKS, on_demand=ON_DEMAND)
def cell(harness: Harness, role: Role, as_json: AsJson = False) -> None:
    """The latest start of a cell: where its tokens are, block by block."""
    _harness(harness)
    payload = obj(_get(CONTEXT_OBS_CELL_PATH, {"harness": harness, "role": role}))
    if as_json:
        output_json(payload)
        return
    latest = obj(payload.get("latest"))
    if not latest:
        _unknown_cell(harness, role)
        emit([f"CELL {harness}/{role}: no measured start in {payload.get('lookback_days', 30)}d"])
        return
    parts = obj(payload.get("parts"))

    def part(name: str) -> str:
        value = obj(parts.get(name))
        if name.startswith("ah_") and value.get("tokens") == 0:
            return f"{_PARTS[name]} none"  # a real start with nothing delivered in that scope, not an unknown
        return f"{_PARTS.get(name, name)} {tok(value.get('tokens'))}" + ("" if value.get("method") in (None, "exact", "derived") else "~")

    names = [n for n in _PARTS if n in parts]
    median = obj(payload.get("median"))
    lines = [f"CELL {harness}/{role} latest start {when(latest.get('at'))}: {tok(latest.get('total'))} "
             f"(harness {tok(latest.get('harness_tokens'))}, ours {tok(latest.get('ours'))}, brief {tok(latest.get('brief'))}) "
             f"{latest.get('version') or UNKNOWN} {latest.get('model') or UNKNOWN}",
             f"  median of {median.get('n', 0)} starts in {median.get('days', payload.get('lookback_days', 30))}d: {tok(median.get('total'))} "
             f"(harness {tok(median.get('harness_tokens'))}, ours {tok(median.get('ours'))}, brief {tok(median.get('brief'))})"
             if median else "  median: not measured",
             "  that latest start: " + ("  ".join(part(n) for n in names) or "not split into parts yet") + "  (~ = estimated from sizes)"]
    blocks = rows(payload.get("blocks"))
    lines.append(f"  {len(blocks)} blocks Agent Hub delivered, {tok(payload.get('blocks_total'))} in all; biggest:")
    for block in blocks[:4]:
        who = block.get("writer_session") or block.get("writer_kind")
        lines.append(f"    {tok(block.get('tokens')):>6} {short(block.get('label') or block.get('block_id'), 36)} {block.get('scope') or UNKNOWN}"
                     + (f" {when(block.get('writer_at'))} {block.get('writer_action') or ''} {short(who, 16)}" if block.get("writer_at") else ""))
    growth = obj(payload.get("growth"))
    if growth.get("measured"):
        lines.append(f"  peak = the largest context a session reached: median {tok(growth.get('median_peak'))}, largest {tok(growth.get('max_peak'))}; "
                     f"{growth.get('compacted')} of {growth.get('sessions')} sessions were compacted")
    move = obj(payload.get("latest_move"))
    if move:
        lines.append(f"  last move {when(move.get('at'))} {tok(move.get('delta'), sign=True)} {pct(move.get('pct'))} cause={move.get('cause')}")
    state = obj(payload.get("state"))
    lines.append(f"  warn {tok(payload.get('budget_warn'))} applies to the first turn; step alert +{payload.get('budget_jump_pct') or UNKNOWN}%"
                 + (f" -> {_flag(state.get('reason'))}" if state.get("reason") else ", ok"))
    emit(lines)


_KIND = {"recent": "the last 7 days against the 7 days before", "step": "a step", "day": "a day's move", "boundary": "a version or config change"}


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
    _harness(harness)
    _unknown_cell(harness, role)
    payload = obj(_get(CONTEXT_OBS_WHY_PATH, {"harness": harness, "role": role, **({"at": at} if at else {})}))
    if as_json:
        output_json(payload)
        return
    before, after, parts = obj(payload.get("before")), obj(payload.get("after")), obj(payload.get("parts"))
    kind = _KIND.get(str(payload.get("kind")), str(payload.get("kind") or ""))
    lines = [f"WHY {harness}/{role} cause={payload.get('cause') or UNKNOWN}, {kind}, at {when(payload.get('at'))}"]
    if payload.get("summary"):
        lines.append("  " + short(payload["summary"], 200))
    if before or after:
        lines.append(f"  before {tok(before.get('total'))} ({before.get('n', 0)} starts, v{before.get('version') or UNKNOWN}, request shape {fp(before.get('config_fp'))})"
                     f" -> after {tok(after.get('total'))} ({after.get('n', 0)} starts, v{after.get('version') or UNKNOWN}, request shape {fp(after.get('config_fp'))})")
    lines.append("  parts " + "  ".join(f"{name} {tok(value, sign=True)}" for name, value in parts.items()))
    for knob in rows(payload.get("knobs"))[:2]:
        lines.append(f"  config file {knob.get('label')} changed {when(knob.get('at'))}")
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
    limit: Annotated[int, typer.Option("--limit", min=1, help="Newest N shown (a text answer stops at 15 lines; --json returns all).")] = 13,
    as_json: AsJson = False,
) -> None:
    """Markers, oldest first, the newest N."""
    _harness(harness)
    stop = datetime.now(UTC)
    found = rows(_get(CONTEXT_OBS_MARKERS_PATH, {"start": (stop - timedelta(days=days)).isoformat(), "end": stop.isoformat(),
                                                  **({"harness": harness} if harness else {})}))
    found = [m for m in found if not kind or m.get("kind") == kind]
    if as_json:
        output_json(found)
        return
    limit = min(limit, MAX_LINES - 1)
    lines = [f"MARKERS last {days}d: {len(found)} found" + (f", newest {limit}" if len(found) > limit else "")]
    lines += [f"  {marker_line(marker)}" for marker in found[-limit:]]
    emit(lines)


budget_app = typer.Typer(help="Budget levels that raise the context alerts. Bare st ctx budget only reads; set, jump and rm change levels.")
app.add_typer(budget_app, name="budget")


@budget_app.callback(invoke_without_command=True)
@usage(surface="st.ctx.budget", cmd="st ctx budget [set HARNESS ROLE TOKENS | jump PCT | rm HARNESS ROLE]",
       when="show warn levels and cells over them; set, jump and rm edit the levels that raise the Nightshift alert",
       task_types=TASKS, on_demand=ON_DEMAND)
def budget(ctx: typer.Context, as_json: AsJson = False) -> None:
    """Show the warn levels and the cells over them. Only reads; set, jump and rm change levels."""
    if ctx.invoked_subcommand is not None:
        return
    levels = rows(_get(CONTEXT_OBS_BUDGETS_PATH))
    states = rows(_get(CONTEXT_OBS_BUDGET_STATE_PATH))
    if as_json:
        output_json({"budgets": levels, "state": states})
        return
    jump = next((r.get("jump_pct") for r in levels if r.get("harness") == "*" and r.get("role") == "*"), None)
    lines = [f"BUDGETS {len(levels)} levels. warn = a median first turn above it raises an alert; step alert = the last 24h of starts "
             f"(same model, brief left out) up {jump or UNKNOWN}% on the 7 days before"]
    lines += table([[f"{r.get('harness')}/{r.get('role')}", f"warn {tok(r.get('warn_tokens'))}", _first_sentence(r.get("note"), 60)] for r in levels[:8]], indent="  ")
    over = [s for s in states if s.get("reason")]
    measured = sum(1 for s in states if s.get("n_recent"))
    lines.append(f"  {len(over)} over, {measured} cells with starts in the last 24h" + (":" if over else ""))
    for state in over[:4]:
        what = (f"24h median {tok(state.get('recent'))} is over warn {tok(state.get('warn_tokens'))}" if state.get("reason") == "warn" else
                f"24h starts {tok(state.get('body_recent'))} vs {tok(state.get('body_baseline'))} the 7 days before ({pct(state.get('body_pct'))})")
        lines.append(f"  {state.get('harness')}/{state.get('cell')} {_flag(state.get('reason'))}: {what}")
    emit(lines)


def _first_sentence(note: Any, width: int) -> str:
    """The note up to its first full stop, so a long note is not cut mid-word."""
    return short(str(note or "").split(". ")[0].rstrip("."), width)


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
