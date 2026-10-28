"""Which shape should a Claude coding step take? Four arms on the frozen 16-check fixture, one ledger, one table.

    backend/.venv/bin/python docs/evaluations/claude-tool-shape-20261027/run.py A B C D
    backend/.venv/bin/python .../run.py --table

Every arm is the unmodified claude CLI on the subscription, Opus 5.5 at "high", through the shipped claude_code
executor; only the launch flags differ:
  A  as shipped: Claude Code's default prompt and full built-in tool set
  B  lean flags: same prompt, tools cut to Read/Edit/Write/Bash/Glob/Grep, no slash commands/skills, no MCP,
     per-machine prompt sections moved out of the system prompt
  E  B with Pi's four tools only (separates the tool list from the prompt swap)
  C  Pi shape: Pi-style ~0.6K-char system prompt replacing Claude Code's, tools Read/Edit/Write/Bash
  D  Agent Hub tools: built-in tools off, Agent Hub's bash/read_file/edit_file/write_file over a local MCP server
Fixture, grading, usage, tool counts and the limit meter are reused from ../multi-model-workflow-20261027/run.py.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("mmw", HERE.parent / "multi-model-workflow-20261027" / "run.py")
mm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mm)  # sets sys.path/cwd for the backend and taps harness events
mm.RESULTS, mm.RUNS = HERE / "results.json", HERE / "runs"

from app.services.workflow_runs.executor_claude_code import ClaudeCodeExecutor  # noqa: E402

PYTHON = sys.executable
LEAN = ["--disable-slash-commands", "--strict-mcp-config"]
PI_PROMPT = """You are an expert coding assistant operating inside a coding agent harness. You help users by reading files, executing commands, editing code, and writing new files.

Available tools:
- Read: Read file contents
- Bash: Execute bash commands (ls, rg, find, tests, git)
- Edit: Make precise file edits with exact text replacement
- Write: Create or overwrite files

Guidelines:
- Use Bash for file operations like ls, rg, find
- Read a file before editing it; use Edit for precise changes and Write only for new files or complete rewrites
- Verify your work by running the relevant checks before you finish
- Be concise in your responses
- Show file paths clearly when working with files"""


def arm_flags(arm: str, worktree: Path) -> list[str]:
    if arm == "A":
        return []
    if arm == "B":
        return [*LEAN, "--exclude-dynamic-system-prompt-sections", "--tools", "Read,Edit,Write,Bash,Glob,Grep"]
    if arm == "E":
        return [*LEAN, "--exclude-dynamic-system-prompt-sections", "--tools", "Read,Edit,Write,Bash"]
    if arm == "C":
        return [*LEAN, "--system-prompt", f"{PI_PROMPT}\n\nWorking directory: {worktree}", "--tools", "Read,Edit,Write,Bash"]
    if arm == "D":
        server = {"command": PYTHON, "args": [str(HERE / "ah_mcp_server.py")], "env": {"AH_TOOL_WORKDIR": str(worktree)}}
        return [*LEAN, "--tools", "", "--mcp-config", json.dumps({"mcpServers": {"ah": server}}),
                "--allowedTools", "mcp__ah__bash,mcp__ah__read_file,mcp__ah__edit_file,mcp__ah__write_file"]
    raise SystemExit(f"unknown arm {arm}")


class ShapedExecutor(ClaudeCodeExecutor):
    def __init__(self, arm: str, worktree: Path) -> None:
        super().__init__()
        self.extra = arm_flags(arm, worktree)

    def command(self, packet, model, binary):
        argv, upstream = super().command(packet, model, binary)
        return [*argv, *self.extra], upstream


async def single(arm: str, rep: int) -> None:
    label = arm if rep == 1 else f"{arm}-r{rep}"
    root = mm.build_fixture(label)
    packet, run_dir = mm.packet_for(root, label, mm.OPUS)
    mm.EVENTS.clear()
    t0 = time.time()
    try:
        result = await ShapedExecutor(arm, root).run(packet, mm.OPUS, root, run_dir, lambda _e: asyncio.sleep(0))
    except Exception as exc:  # setup/harness failure: recorded, not retried
        mm.record({"label": label, "arm": arm, "status": "crashed", "error": repr(exc)[:500], "passed": "unknown", "total": 16})
        return
    u = result.usage or {}
    row = {"label": label, "arm": arm, "flags": arm_flags(arm, root), "status": result.status, "error": result.error,
           "answered_by": list(result.served_models), "wall_s": round(time.time() - t0, 1)}
    if all(k in u for k in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")):
        row |= mm.usage_cols(u) | {"cost_usd": mm.cost(mm.OPUS, u)}
    else:
        row |= {k: "unknown" for k in ("input", "cache_read", "cache_write", "output", "cost_usd")}
    row |= dict(zip(("tool_calls", "tool_failed"), mm.tool_stats(mm.EVENTS)))
    meter = mm.limit_meter(mm.EVENTS)
    row["claude_5h_delta_pts"] = round((meter[-1] - meter[0]) * 100, 1) if len(meter) >= 2 else None
    init = next((r for _, r in mm.EVENTS if r.get("type") == "system" and r.get("subtype") == "init"), {})
    row["tools_offered"], row["mcp_servers"] = init.get("tools"), init.get("mcp_servers")
    with (mm.RUNS / f"{label}.events.jsonl").open("w") as fh:
        fh.writelines(json.dumps(r) + "\n" for _, r in mm.EVENTS)
    row["passed"], row["total"] = mm.grade(root)
    mm.record(row)


async def main(args: list[str]) -> None:
    if args == ["--table"]:
        print(mm.table())
        return
    await mm.load_catalog()
    for arg in args:
        arm, _, rep = arg.partition("-r")
        await single(arm, int(rep or 1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
