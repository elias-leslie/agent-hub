"""Multi-model workflow evaluation: six runs, one ledger, one table (see PLAN.md).

    backend/.venv/bin/python docs/evaluations/multi-model-workflow-20261027/run.py 3b 2 3 1 4 5
    backend/.venv/bin/python .../run.py --repeat     # PLAN.md repeat rule: pairs of runs 1-3b within 15%
    backend/.venv/bin/python .../run.py --table      # print the table from results.json

Runs 1-3b call the shipped step executors directly on the frozen 16-check fixture; runs 4 and 5 go through the
workflow engine in-process (test hooks switched on for this process only). Every arm uses thinking level "high".
Raw harness events are only read to count tool calls and the Claude limit meter; usage comes from the executors.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EVAL = HERE.parent
FIXTURE = EVAL / "harness-efficiency-20261022"
sys.path[:0] = [str(FIXTURE), str(REPO / "backend")]
import os  # noqa: E402

os.chdir(REPO / "backend")

import prepare as fx  # noqa: E402

from app.constants.catalog import get_model_entry, replace_runtime_model_catalog  # noqa: E402
from app.db import async_session  # noqa: E402
from app.services.model_catalog_service import get_model_aliases, get_model_catalog_entries  # noqa: E402
from app.services.workflow_runs import executor_common as ec  # noqa: E402
from app.services.workflow_runs.engine import EngineDeps, advance_run, create_run, get_run_view  # noqa: E402
from app.services.workflow_runs.executor_agent_hub import AgentHubExecutor, text_of  # noqa: E402,F401
from app.services.workflow_runs.executors import get_executor  # noqa: E402
from app.services.workflow_runs.packet import AttemptRef, GitState, build_packet  # noqa: E402
from app.services.workflow_runs.schemas import RunDefinition  # noqa: E402

RESULTS = HERE / "results.json"
RUNS = HERE / "runs"
OPUS, SOL = "claude-opus-5-5", "codex/gpt-6.1-sol"
GOAL = "Fix windows.py and paging.py to meet README.md and write inspection.json (frozen 16-check fixture)."
# arm -> (description, executor kind, model)
ARMS = {
    "1": ("Claude Code / Opus 5.5", "claude_code", OPUS),
    "2": ("Codex / gpt-6.1-sol", "codex", SOL),
    "3": ("Pi / gpt-6.1-sol", "pi", SOL),
    "3b": ("Agent Hub harness (coder) / gpt-6.1-sol", "agent_hub", SOL),
}
STEP2 = (
    "Review the previous step's changes against README.md, run the acceptance check from README.md, "
    "and fix any defects you find. Do not edit the acceptance program, README, catalog, configuration or frozen digest list."
)

# --- instrumentation: read-only tap on the harness event stream ------------------------------------------------
EVENTS: list[tuple[float, dict]] = []
_records = ec.HarnessProcess.records


async def _tapped(self):
    async for record in _records(self):
        EVENTS.append((time.time(), record))
        yield record


ec.HarnessProcess.records = _tapped


def tool_stats(events) -> tuple[int, int]:
    """(tool calls, failed) from claude stream-json, codex exec --json or pi rpc records."""
    seen, failed = set(), set()
    for _, e in events:
        kind = e.get("type")
        content = (e.get("message") or {}).get("content")
        if kind == "assistant" and isinstance(content, list):
            seen |= {b["id"] for b in content if b.get("type") == "tool_use"}
        elif kind == "user" and isinstance(content, list):
            failed |= {b["tool_use_id"] for b in content if b.get("type") == "tool_result" and b.get("is_error")}
        elif kind == "item.completed":
            item = e.get("item") or {}
            if item.get("type") in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
                seen.add(item.get("id"))
                if item.get("status") == "failed" or item.get("exit_code") not in (0, None):
                    failed.add(item.get("id"))
        elif kind == "tool_execution_end":
            seen.add(e.get("toolCallId"))
            if e.get("isError"):
                failed.add(e.get("toolCallId"))
    return len(seen), len(failed & seen)


def limit_meter(events) -> list[float]:
    out = []
    for _, e in events:
        if e.get("type") == "rate_limit_event":
            window = ((e.get("rate_limit_info") or {}).get("unifiedWindows") or {}).get("five_hour") or {}
            if isinstance(window.get("utilization"), (int, float)):
                out.append(window["utilization"])
    return out


# --- prices ------------------------------------------------------------------------------------------------
PRICES: dict[str, dict] = {}


async def load_catalog() -> None:
    from app.services.credential_manager import get_credential_manager
    async with async_session() as db:  # same startup hydration as the service: provider credentials and catalog
        await get_credential_manager().load(db)
        entries = await get_model_catalog_entries(db)
        replace_runtime_model_catalog(entries, await get_model_aliases(db))
    opus = get_model_entry(OPUS).cost
    sol = json.loads((FIXTURE / "prices.json").read_text())["rates_per_million"]
    PRICES[OPUS] = {"input": opus.input_per_m, "cache_read": opus.cache_read_per_million,
                    "cache_write": opus.cache_write_per_million, "output": opus.output_per_m}
    # The catalog carries no USD price for gpt-6.1-sol (credits only: 50/2.5/250 per M = $2/$0.10/$10 at 25 credits/$);
    # the pinned schedule from the previous evaluation states the same rates in USD.
    PRICES[SOL] = {"input": sol["uncached_input"], "cache_read": sol["cached_read"], "cache_write": sol["cache_write_30m"],
                   "output": sol["output_including_reasoning"]}


def cost(model: str, u: dict) -> float:
    p = PRICES[model]
    return round((u["input_tokens"] * p["input"] + u["cache_read_tokens"] * p["cache_read"]
                  + u["cache_write_tokens"] * p["cache_write"] + u["output_tokens"] * p["output"]) / 1e6, 4)


# --- fixture + grading -------------------------------------------------------------------------------------
def build_fixture(label: str) -> Path:
    root = RUNS / label
    root.mkdir(parents=True)  # a label is used once
    for name, content in fx.FILES.items():
        (root / name).write_text(content)
    (root / "README.md").write_text(fx.README.replace("ACCEPTANCE", str(FIXTURE / "acceptance.py")))
    (root / "condition.json").write_text(json.dumps({"task": fx.TASK}))
    (root / "frozen.json").write_text(json.dumps(
        {f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in ["catalog.py", "README.md", "condition.json"]}))
    for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root


def grade(root: Path):
    try:
        out = subprocess.run([sys.executable, str(FIXTURE / "acceptance.py"), str(root)], capture_output=True, text=True, timeout=120)
        result = json.loads(out.stdout)
        return int(result["passed"]), int(result["total"])
    except Exception:
        return "unknown", 16


def packet_for(root: Path, label: str, model: str):
    run_dir = RUNS / f"{label}.run"
    run_dir.mkdir()
    window = get_model_entry(model).context_window
    packet = build_packet(run_goal=GOAL, step_key="implement", instructions=fx.TASK, acceptance=[], git=GitState(),
                          prior_steps=[], run_dir=str(run_dir), context_window=window, budget_fraction=0.25)
    attempt = AttemptRef(str(uuid.uuid4()), str(uuid.uuid4()), "agent-hub", "coder")
    return replace(packet, thinking_level="high", attempt=attempt), run_dir


# --- ledger ------------------------------------------------------------------------------------------------
def ledger() -> list[dict]:
    return json.loads(RESULTS.read_text()) if RESULTS.exists() else []


def record(row: dict) -> None:
    rows = ledger()
    assert row["label"] not in {r["label"] for r in rows}, f"duplicate label {row['label']}"
    rows.append(row)
    RESULTS.write_text(json.dumps(rows, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps({k: row.get(k) for k in ("label", "status", "passed", "input", "cache_read", "cache_write", "output",
                                              "cost_usd", "wall_s", "tool_calls", "tool_failed", "answered_by", "error")}), flush=True)


def usage_cols(u: dict) -> dict:
    return {"input": u["input_tokens"], "cache_read": u["cache_read_tokens"], "cache_write": u["cache_write_tokens"],
            "output": u["output_tokens"]}


# --- runs 1-3b ---------------------------------------------------------------------------------------------
async def single(arm: str, rep: int) -> None:
    desc, kind, model = ARMS[arm]
    label = arm if rep == 1 else f"{arm}-r{rep}"
    root = build_fixture(label)
    packet, run_dir = packet_for(root, label, model)
    executor = get_executor(kind)
    held: dict = {}
    if kind == "agent_hub":
        async def loader(slug):  # same agent, "high" like every other arm
            from app.services.workflow_runs.executor_agent_hub import load_agent
            agent = await load_agent(slug)
            return SimpleNamespace(temperature=agent.temperature, thinking_level="high")

        async def complete(**kw):
            from app.api.complete.core import complete_internal
            from app.constants.projects import is_cache_stale, refresh_project_cache
            if is_cache_stale():
                await refresh_project_cache()
            held["result"] = await complete_internal(**kw)
            return held["result"]

        executor = AgentHubExecutor(complete=complete, agent_loader=loader)
    EVENTS.clear()

    async def on_event(_e):
        pass

    t0 = time.time()
    try:
        result = await executor.run(packet, model, root, run_dir, on_event)
    except Exception as exc:  # setup/harness failure: recorded, not retried
        record({"label": label, "arm": arm, "desc": desc, "status": "crashed", "error": repr(exc)[:500], "passed": "unknown", "total": 16})
        return
    wall = round(time.time() - t0, 1)
    u = result.usage or {}
    row = {"label": label, "arm": arm, "desc": desc, "model": model, "status": result.status, "error": result.error,
           "answered_by": list(result.served_models), "wall_s": wall, "native_session_id": result.native_session_id,
           "handoff_summary": ((result.handoff or {}).get("summary") or "")[:300], "outcome": str(result.outcome) if result.outcome else None}
    if all(k in u for k in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")):
        row |= usage_cols(u) | {"cost_usd": cost(model, u), "reasoning": u.get("reasoning_tokens")}
    else:
        row |= {"input": "unknown", "cache_read": "unknown", "cache_write": "unknown", "output": "unknown", "cost_usd": "unknown"}
    if kind == "agent_hub":
        msgs = list(getattr(held.get("result"), "usage_messages", None) or [])
        calls = sum(1 for m in msgs for b in m.content if type(b).__name__ == "ToolCall")
        row |= {"tool_calls": calls, "tool_failed": "unknown"}
    else:
        row |= dict(zip(("tool_calls", "tool_failed"), tool_stats(EVENTS)))
    row["cli_cost_usd"] = u.get("total_cost_usd")  # Claude CLI list cost (bills 1h cache writes at the higher rate)
    meter = limit_meter(EVENTS)
    row["claude_5h_delta_pts"] = round((meter[-1] - meter[0]) * 100, 1) if len(meter) >= 2 and kind == "claude_code" else None
    row["passed"], row["total"] = grade(root)
    (root.parent / f"{label}.result.json").write_text(json.dumps(row, default=str))
    record(row)


# --- runs 4 and 5: through the workflow engine ---------------------------------------------------------------
async def workflow(arm: str) -> None:
    label = f"{arm}"
    root = build_fixture(label)
    if arm == "4":
        steps = [
            {"key": "implement", "instructions": fx.TASK, "agent_slug": "coder", "model_override": OPUS,
             "allowed_models": [OPUS], "executor": "claude_code", "max_attempts": 1},
            {"key": "review_fix", "instructions": STEP2, "agent_slug": "coder", "model_override": SOL,
             "allowed_models": [SOL], "executor": "codex", "max_attempts": 1},
        ]
    else:
        steps = [{"key": "implement", "instructions": fx.TASK, "agent_slug": "coder", "model_override": OPUS,
                  "test_hooks": {"refuse_after_turn": 1, "refusal_category": "cyber"}}]
    attempts: list[dict] = []

    class Traced:
        def __init__(self, inner):
            self.inner = inner

        async def run(self, packet, model, worktree, run_dir, on_event):
            at = {"step": packet.step_key, "model": model, "packet_tokens": packet.estimated_tokens,
                  "packet_chars": len(packet.render()), "partial": packet.partial is not None, "start": time.time(), "first_event": None}
            attempts.append(at)
            EVENTS.clear()

            async def tap(event):
                at["first_event"] = at["first_event"] or time.time()
                await on_event(event)

            result = await self.inner.run(packet, model, worktree, run_dir, tap)
            at["end"] = time.time()
            at["result"] = result
            at["tools"] = tool_stats(EVENTS)
            at["meter"] = limit_meter(EVENTS)
            return result

    async def high(_slug):
        return "high"

    deps = EngineDeps(get_executor=lambda kind: Traced(get_executor(kind)), agent_thinking_level=high,
                      test_hooks_on=lambda: arm == "5")  # hooks on for this process only; live service config untouched
    definition = RunDefinition(goal=GOAL, project_id="agent-hub", repo_path=str(root), request_id=f"mmw-20261027-{label}", steps=steps)
    t0 = time.time()
    try:
        async with async_session() as db:
            run_id, _ = await create_run(db, definition, deps=deps)
        while (await advance_run(run_id, deps=deps)).get("next") == "continue":
            pass
        async with async_session() as db:
            view = await get_run_view(db, run_id)
    except Exception as exc:
        record({"label": label, "arm": arm, "status": "crashed", "error": repr(exc)[:500], "passed": "unknown", "total": 16})
        return
    wall = round(time.time() - t0, 1)
    worktree = Path(view["worktree"])
    kept = worktree.exists()
    tot = {"input_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "output_tokens": 0}
    total_cost, calls, failed, per_attempt, meter = 0.0, 0, 0, [], []
    for at in attempts:
        u = at["result"].usage or {}
        for k in tot:
            tot[k] += u.get(k, 0)
        c = cost(at["model"], u) if "input_tokens" in u else 0.0
        total_cost += c
        calls += at["tools"][0]
        failed += at["tools"][1]
        meter += at["meter"]
        per_attempt.append({"step": at["step"], "model": at["model"], "status": at["result"].status, "error": at["result"].error,
                            "served": list(at["result"].served_models), "usage": u, "cost_usd": c, "packet_tokens": at["packet_tokens"],
                            "packet_chars": at["packet_chars"], "partial_progress": at["partial"], "tool_calls": at["tools"][0],
                            "seconds": round(at["end"] - at["start"], 1)})
    row = {"label": label, "arm": arm, "desc": {"4": "Workflow: Claude Code/Opus implement -> Codex/gpt-6.1-sol review_fix",
                                                 "5": "Workflow: Claude Code/Opus + injected refusal after turn 1 -> chain takeover"}[arm],
           "status": view["state"], "answered_by": [s["answered_by"] for s in view["steps"]], "wall_s": wall,
           "input": tot["input_tokens"], "cache_read": tot["cache_read_tokens"], "cache_write": tot["cache_write_tokens"],
           "output": tot["output_tokens"], "cost_usd": round(total_cost, 4), "tool_calls": calls, "tool_failed": failed,
           "claude_5h_delta_pts": round((meter[-1] - meter[0]) * 100, 1) if len(meter) >= 2 else None,
           "attempts": per_attempt, "worktree_kept": kept, "run_id": run_id,
           "step_states": [(s["key"], s["status"], s["attempts"], s["hops"]) for s in view["steps"]], "failure": view.get("failure"),
           "pause": view.get("pause")}
    if arm == "4":
        sha = {s["key"]: s["checkpoint_sha"] for s in view["steps"]}
        if sha.get("implement") and sha.get("review_fix"):
            stat = subprocess.run(["git", "-C", str(worktree), "diff", "--numstat", sha["implement"], sha["review_fix"], "--",
                                   "windows.py", "paging.py", "inspection.json"], capture_output=True, text=True).stdout
            row["step2_rewrote_lines"] = sum(int(a) + int(b) for a, b, _ in (l.split("\t") for l in stat.splitlines()) if a.isdigit() and b.isdigit())
        else:
            row["step2_rewrote_lines"] = "unknown"
    if arm == "5" and len(attempts) >= 2:
        row["refusal_to_next_first_event_s"] = (round(attempts[1]["first_event"] - attempts[0]["end"], 1)
                                                if attempts[1]["first_event"] else "unknown")
    row["passed"], row["total"] = grade(worktree) if kept else ("unknown", 16)
    (root.parent / f"{label}.result.json").write_text(json.dumps(row, default=str))
    record(row)


# --- table / repeat rule -----------------------------------------------------------------------------------
def total_tokens(r):
    return sum(r[k] for k in ("input", "cache_read", "cache_write", "output")) if all(isinstance(r.get(k), int) for k in ("input", "cache_read", "cache_write", "output")) else None


def table() -> str:
    head = "| run | passed | input | cache read | cache write | output | cost USD | 5h delta (pts) | wall s | tools (failed) | answered by |"
    lines = [head, "|" + "---|" * 11]
    for r in ledger():
        lines.append(f"| {r['label']} | {r.get('passed')}/{r.get('total')} | {r.get('input')} | {r.get('cache_read')} | {r.get('cache_write')} | "
                     f"{r.get('output')} | {r.get('cost_usd')} | {r.get('claude_5h_delta_pts')} | {r.get('wall_s')} | "
                     f"{r.get('tool_calls')} ({r.get('tool_failed')}) | {r.get('answered_by')} |")
    return "\n".join(lines)


def repeat_arms() -> list[str]:
    """PLAN.md: only if two of runs 1-3b come within 15% on tokens or time; those two run once more."""
    rows = {r["arm"]: r for r in ledger() if r["arm"] in ARMS and r["label"] == r["arm"] and r.get("status") == "completed"}
    pairs = set()
    for a in rows:
        for b in rows:
            if a < b:
                for f in (total_tokens, lambda r: r.get("wall_s")):
                    x, y = f(rows[a]), f(rows[b])
                    if x and y and abs(x - y) / max(x, y) <= 0.15:
                        pairs.add((a, b))
    return sorted({arm for pair in pairs for arm in pair}) if pairs else []


async def main(args: list[str]) -> None:
    if args == ["--table"]:
        print(table())
        return
    await load_catalog()
    if args == ["--repeat"]:
        arms = repeat_arms()
        print("repeat arms:", arms)
        for arm in arms:
            await single(arm, 2)
        return
    for arm in args:
        await (single(arm, 1) if arm in ARMS else workflow(arm))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
