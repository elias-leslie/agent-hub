"""First-turn context capture: backfill and baseline report.

    python -m app.cli.context_backfill backfill [--days 30]
    python -m app.cli.context_backfill report [--as-of 2026-11-01T18:00:00Z] [--days 7]

`backfill` imports delivery contract files and measures the first turn of every session in the window (the collector
runs it once by itself after deploy; this reruns it). `report` prints medians per harness and role and checks them
against the DESIGN section 2 baseline, and shows the config steps of the Claude implementation lane. Both use
AGENT_HUB_DB_URL, so pointing that at a scratch database leaves the real one untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from app.db import async_session
from app.services.context_observability import baseline, capture

TOLERANCE = 0.03
LANE_TRIM_AT = datetime(2026, 11, 1, 14, 53, tzinfo=UTC)
# The same Claude Code request-shape change trimmed blank-slate sessions; a fixed time keeps the before/after check honest.
BLANK_TRIM_AT = LANE_TRIM_AT
SUBAGENT_SINCE = datetime(2026, 11, 1, tzinfo=UTC)
CODEX_LANE_AS_OF = datetime(2026, 10, 31, tzinfo=UTC)

# DESIGN section 2 numbers (tokens). part: total | harness | ours. A (low, high) expectation is a range.
# Lane-after harness is DESIGN's total minus its 5.3-5.9K ours range, so it is a range too.
# Codex harness-own is DESIGN's "~14K tools+base + skills list ~2.7K"; our harness part is everything but ours and the brief.
# Codex lane ours was measured on Oct 30 data (n=12); the delivery grew 5.1-5.6K -> 5.8-6.2K on Oct 31, so those rows are
# checked as of CODEX_LANE_AS_OF.
EXPECTED = (
    ("claude", "coordinator / owner-opened", "total", 47_900), ("claude", "coordinator / owner-opened", "harness", 42_000),
    ("claude", "coordinator / owner-opened", "ours", 5_600),
    ("claude", "lane impl before trim", "total", 48_300), ("claude", "lane impl before trim", "harness", 42_400),
    ("claude", "lane impl before trim", "ours", 5_900),
    ("claude", "lane impl after trim", "total", 24_300), ("claude", "lane impl after trim", "harness", (18_300, 18_900)),
    ("claude", "lane impl after trim", "ours", (5_300, 5_900)),
    ("claude", "hunter", "total", 29_100), ("claude", "hunter", "harness", 23_000), ("claude", "hunter", "ours", 5_000),
    ("claude", "tester (user-tester subagent)", "total", 13_300),
    ("claude", "blank before", "total", 40_400), ("claude", "blank after", "total", (9_800, 11_700)),
    ("claude", "general-purpose subagent", "total", 34_600), ("claude", "code-reviewer subagent", "total", 13_400),
    ("claude", "Explore subagent", "total", 12_000),
    ("codex", "coordinator", "total", 22_300), ("codex", "lane (implementation)", "total", 22_100),
    ("codex", "review", "total", 20_600), ("codex", "hunter", "total", 23_100), ("codex", "blank", "total", 14_100),
    ("codex", "lane (implementation)", "harness", 16_700), ("codex", "lane (implementation)", "ours", 5_500),
    # Pi 1.4.0 with deepseek-v4.1-flash. "other" is the delivery's work role "other".
    ("pi", "coordinator", "total", 8_000), ("pi", "hunter", "total", 8_200), ("pi", "review", "total", 7_100),
    ("pi", "other", "total", 8_000), ("pi", "no delivery (probes)", "total", 2_000),
)
PI_MODEL = "deepseek-v4.1-flash"


def _is_launched(r: baseline.FirstTurn) -> bool:
    """A launch that carries a delivery and a role: interactive or lane (project) or a headless `codex exec` lane."""
    return r.launch_mode in ("project", "exec")


def _is_project(r: baseline.FirstTurn) -> bool:
    return r.launch_mode == "project"


def baseline_groups(rows: list[baseline.FirstTurn]) -> dict[tuple[str, str], list[baseline.FirstTurn]]:
    """The DESIGN section 2 rows as filters over measured first turns."""
    claude = [r for r in rows if r.harness == "claude"]
    codex = [r for r in rows if r.harness == "codex"]
    pi = [r for r in rows if r.harness == "pi" and r.model == PI_MODEL]
    lane_impl = [r for r in claude if _is_project(r) and r.role == "implementation"]
    blank = [r for r in claude if r.launch_mode == "blank"]
    sub_rows = [r for r in claude if r.at >= SUBAGENT_SINCE]
    return {
        ("claude", "coordinator / owner-opened"): [
            r for r in claude if _is_project(r) and (r.role == "coordinator" or (r.role is None and r.delivery_id))
        ],
        ("claude", "lane impl before trim"): [r for r in lane_impl if r.at < LANE_TRIM_AT],
        ("claude", "lane impl after trim"): [r for r in lane_impl if r.at >= LANE_TRIM_AT],
        ("claude", "hunter"): [r for r in claude if _is_project(r) and r.role == "hunting"],
        ("claude", "tester (user-tester subagent)"): [r for r in claude if r.launch_mode == "subagent:user-tester"],
        ("claude", "blank before"): [r for r in blank if r.at < BLANK_TRIM_AT],
        ("claude", "blank after"): [r for r in blank if r.at >= BLANK_TRIM_AT],
        ("claude", "general-purpose subagent"): [r for r in sub_rows if r.launch_mode == "subagent:general-purpose"],
        ("claude", "code-reviewer subagent"): [r for r in sub_rows if r.launch_mode == "subagent:code-reviewer"],
        ("claude", "Explore subagent"): [r for r in sub_rows if r.launch_mode == "subagent:Explore"],
        # Interactive Neri coordinators only: the headless `codex exec` coordinator runs (workflow proofs) are another launch mode.
        # Codex lanes, reviews and hunters are often `codex exec` launches, so those rows take both modes.
        ("codex", "coordinator"): [r for r in codex if _is_project(r) and r.role == "coordinator"],
        ("codex", "lane (implementation)"): [r for r in codex if _is_launched(r) and r.role == "implementation"],
        ("codex", "review"): [r for r in codex if _is_launched(r) and r.role == "review"],
        ("codex", "hunter"): [r for r in codex if _is_launched(r) and r.role == "hunting"],
        ("codex", "blank"): [r for r in codex if r.launch_mode == "blank"],
        ("pi", "coordinator"): [r for r in pi if r.delivery_id and r.role == "coordinator"],
        ("pi", "hunter"): [r for r in pi if r.delivery_id and r.role == "hunting"],
        ("pi", "review"): [r for r in pi if r.delivery_id and r.role == "review"],
        ("pi", "other"): [r for r in pi if r.delivery_id and r.role == "other"],
        ("pi", "no delivery (probes)"): [r for r in pi if not r.delivery_id],
    }


def check_row(value: int | None, expected: int | tuple[int, int]) -> tuple[bool, str]:
    if value is None:
        return False, "unknown"
    if isinstance(expected, tuple):
        low, high = expected
        return low * (1 - TOLERANCE) <= value <= high * (1 + TOLERANCE), f"{low}-{high}"
    return abs(value - expected) <= expected * TOLERANCE, str(expected)


def _fmt(value: int | None) -> str:
    return "-" if value is None else f"{value / 1000:.1f}K"


async def report(as_of: datetime, days: int) -> int:
    async with async_session() as db:
        since = as_of - timedelta(days=days)
        rows = await baseline.load_first_turns(db, since=since, until=as_of)
    groups = baseline_groups(rows)
    # Pi rows: DESIGN's coordinator n=3 counted a blank-slate session bound to a coordinator delivery that cannot fit in
    # its 1.7K first turn. The two real sessions are 8.0K and 8.4K; the usual median (their mean) is the fair read.
    summaries = {key: baseline.summarize(items, mean_of_middle=key[0] == "pi") for key, items in groups.items()}
    failures = 0
    print(f"first turns {since:%Y-%m-%d %H:%MZ} .. {as_of:%Y-%m-%d %H:%MZ}: {len(rows)} measured")
    print(f"{'harness':7} {'row':32} {'n':>4} {'total':>8} {'harness':>8} {'ours':>7} {'brief':>7}")
    for (harness, name), s in summaries.items():
        print(f"{harness:7} {name:32} {s['n']:>4} {_fmt(s['total']):>8} {_fmt(s['harness']):>8} {_fmt(s['ours']):>7} {_fmt(s['brief']):>7}")
    print(f"\nacceptance (DESIGN section 2, +-{TOLERANCE:.0%})")
    for harness, name, part, expected in EXPECTED:
        s = summaries.get((harness, name))
        if (harness, name) == ("codex", "lane (implementation)") and part in ("harness", "ours"):
            s = baseline.summarize([r for r in groups[(harness, name)] if r.at < CODEX_LANE_AS_OF])
        value = s[part] if s else None
        ok, want = check_row(value, expected)
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'} {harness:6} {name:30} {part:8} got {_fmt(value):>7} want {want:>12} n={s['n'] if s else 0}")
    print("\nclaude implementation lane: config steps (shapeHash) per model")
    lane = [r for r in rows if r.harness == "claude" and _is_project(r) and r.role == "implementation"]
    for model, items in baseline.group_by(lane, lambda r: r.model).items():
        for step in baseline.config_steps(items):
            print(json.dumps({"model": model, **step, "at": step["at"].isoformat()}, default=str))
    return failures


async def run_backfill(days: int) -> dict[str, int]:
    async with async_session() as db:
        summary = await capture.backfill(db, days=days)
        await db.commit()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    back = sub.add_parser("backfill")
    back.add_argument("--days", type=int, default=capture.BACKFILL_DAYS)
    rep = sub.add_parser("report")
    rep.add_argument("--as-of", default=None, help="UTC end of the window (default: now)")
    rep.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.command == "backfill":
        print(json.dumps(asyncio.run(run_backfill(args.days))), flush=True)
        return
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else datetime.now(UTC)
    raise SystemExit(1 if asyncio.run(report(as_of, args.days)) else 0)


if __name__ == "__main__":
    main()
