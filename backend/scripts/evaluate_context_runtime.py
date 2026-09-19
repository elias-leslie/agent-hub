"""Repeatable native read-only development-task comparison; never changes sources.

Uses a catalog-backed agent and the installed canonical delivery client. The
counterfactual explicitly activates the research workflow; it is not a claim
that a historical full prompt was reconstructed. Native instructions remain.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db import async_session
from app.models.agent import Agent
from app.models.model_catalog import ModelCatalogEntry
from app.services.context_governance import record
from app.services.context_policy import semantic_hash

ROOT = Path(__file__).resolve().parents[2]
CASES: list[dict[str, Any]] = [
    {"id": "scope", "prompt": "Locate the function deciding whether a project-scoped context prompt applies. Explain how explicit workflows and consumer exclusions interact, citing the file and function.", "expected": ["policy_match", "context_policy.py"]},
    {"id": "retrieval", "prompt": "Locate the test proving that an on-demand context prompt initially exposes an index rather than its full body. Explain how that test requests the full body, citing the test and request field.", "expected": ["test_on_demand_index", "requested_source_ids"]},
    {"id": "draft", "prompt": "Locate the Runtime Context UI save flow and its server-side stale-update protection. Explain the preview gate and revision check with file/function references.", "expected": ["ContextManager", "expected_revision"]},
]


async def command(*args: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*args, cwd=ROOT, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(), err.decode()


async def checkout_snapshot() -> list[dict[str, str]]:
    _, paths, _ = await command("git", "ls-files", "--cached", "--others", "--exclude-standard", "backend/app", "backend/tests", "frontend/src", "backend/scripts/evaluate_context_runtime.py")
    import hashlib
    return [{"path": name, "sha256": hashlib.sha256(await asyncio.to_thread((ROOT/name).read_bytes)).hexdigest()} for name in sorted(set(paths.splitlines())) if (ROOT/name).is_file()]


async def evaluate(agent_slug: str, output: Path, execute: bool) -> None:
    async with async_session() as db:
        agent = (await db.execute(select(Agent).where(Agent.slug == agent_slug, Agent.is_active.is_(True)))).scalar_one()
        model = await db.get(ModelCatalogEntry, agent.primary_model_id)
        if model is None or model.provider != "codex" or not model.supports_tool_execution:
            raise ValueError("Select an active Codex agent with catalog tool support")
        model_id, thinking = model.id, agent.thinking_level
        native_model = model_id.removeprefix("codex/")
        registration = {"agent_slug": agent_slug, "model": model_id, "thinking": thinking, "cases": CASES,
            "scope": "Three representative read-only development inspections; no code-writing generalization",
            "comparison": "Current scoped delivery versus the same delivery with Security Research explicitly active",
            "execution_order": [[case["id"], variant] for i, case in enumerate(CASES) for variant in (["scoped", "research_active"] if i % 2 == 0 else ["research_active", "scoped"])],
            "expected_first_tool": "st search", "retries": "none", "user_interventions": 0,
            "correctness": "Predeclared answer anchors plus retained final answer for human assessment",
            "unnecessary_calls": "Report commands and failed calls; necessity requires human interpretation, not token counts",
            "revision": (await command("git", "rev-parse", "HEAD"))[1].strip(), "checkout_sources": await checkout_snapshot()}
        if not execute:
            print(json.dumps(registration))
            return
        registration["record_id"] = await record(db, "evaluation_registration", "context-runtime-evaluation", registration)
        await db.commit()
    await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
    evidence = {"registration": registration, "runs": [], "model_receipt": "Native launch configuration and tool transcript observed; no hidden provider request inspection"}
    private = output.parent / "native-transcripts"
    await asyncio.to_thread(private.mkdir, parents=True, exist_ok=True)
    for case_id, variant in registration["execution_order"]:
        if await checkout_snapshot() != registration["checkout_sources"]:
            raise RuntimeError("Evaluation checkout changed; retained partial results cannot qualify this configuration")
        case = next(c for c in CASES if c["id"] == case_id)
        env = dict(os.environ)
        env["AGENT_HUB_WORKFLOWS"] = "security-research" if variant == "research_active" else ""
        client = str(ROOT / "integrations/context-delivery/bin/agent-hub-context-client")
        code, out, err = await command(client, "deliver", "--surface", "codex", "--capability", "bash", "--project", "agent-hub", "--cwd", str(ROOT), "--agent-slug", agent_slug, "--model", native_model, "--query", "startup context", "--emit", "descriptor", env=env)
        descriptor = json.loads(out)
        if code or descriptor["status"] != "ok":
            raise RuntimeError(f"Canonical delivery unavailable: {err}")
        rendered = await asyncio.to_thread(Path(descriptor["text_path"]).read_text)
        contract = json.loads(await asyncio.to_thread(Path(descriptor["contract_path"]).read_text))
        env.update({"AGENT_HUB_CONTEXT_PREINJECTED_HASH": descriptor["payload_hash"], "AGENT_HUB_CONTEXT_PREINJECTED_TEXT": descriptor["text_path"], "AGENT_HUB_CONTEXT_PREINJECTED_CONTRACT": descriptor["contract_path"]})
        prompt = "This is a bounded read-only evaluation, not an implementation assignment. Do not change files, run network requests, read credentials, delegate, create tasks, or start services. Inspect only source and tests needed to answer. " + case["prompt"]
        args = [str(Path.home()/".local/bin/codex-real"), "exec", "--json", "--ephemeral", "--sandbox", "read-only", "--model", native_model, "-c", "developer_instructions=" + json.dumps(rendered)]
        if thinking:
            args.extend(["-c", "model_reasoning_effort=" + json.dumps(thinking)])
        start = time.monotonic()
        code, transcript, stderr = await command(*args, prompt, env=env)
        elapsed = time.monotonic() - start
        events = []
        for line in transcript.splitlines():
            with suppress(ValueError):
                events.append(json.loads(line))
        commands = [e["item"] for e in events if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "command_execution"]
        finals = [e["item"]["text"] for e in events if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"]
        usage = [e.get("usage", {}) for e in events if e.get("type") == "turn.completed"]
        first = commands[0].get("command") if commands else None
        final = finals[-1] if finals else ""
        run = {"case": case_id, "variant": variant, "exit_code": code, "elapsed_seconds": elapsed,
            "delivery_id": contract["delivery_id"], "payload_hash": descriptor["payload_hash"], "generated_tokens": contract["estimated_tokens"],
            "first_command": first, "first_tool_correct": bool(first and "st search" in first),
            "commands": [{k: c.get(k) for k in ("command", "exit_code", "status")} for c in commands],
            "discovery_calls": sum("st search" in c.get("command", "") for c in commands),
            "failed_calls": sum(bool(c.get("exit_code")) for c in commands), "user_interventions": 0,
            "usage": usage, "uncached_input_tokens": sum(u.get("input_tokens", 0) - u.get("cached_input_tokens", 0) for u in usage),
            "answer_anchors_match": all(anchor.lower() in final.lower() for anchor in case["expected"]), "final": final,
            "transcript_sha256": semantic_hash(transcript), "stderr": stderr}
        await asyncio.to_thread((private/f"{case_id}-{variant}.jsonl").write_text, transcript)
        run["checkout_unchanged"] = await checkout_snapshot() == registration["checkout_sources"]
        evidence["runs"].append(run)
        await asyncio.to_thread(output.write_text, json.dumps(evidence, indent=2) + "\n")
        if not run["checkout_unchanged"]:
            raise RuntimeError("Evaluation checkout changed during this run; result retained as unqualified")
        print(json.dumps({k: run[k] for k in ("case", "variant", "exit_code", "elapsed_seconds", "first_tool_correct", "answer_anchors_match", "usage")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    asyncio.run(evaluate(args.agent, args.output, args.execute))
