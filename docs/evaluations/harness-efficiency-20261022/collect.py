"""Content-free receipts from exact native subjects; no transcript copies."""

import hashlib
import json
import os
import re
import statistics
from datetime import datetime
from pathlib import Path

BASE = Path(os.environ.get("HARNESS_TRIAL_ROOT", "/srv/workspaces/agent-reviews/harness-efficiency-20261022"))
RATES = json.loads((BASE / "prices.json").read_text())["rates_per_million"]
CODEX_DAY = Path.home() / ".codex/sessions/2026/10/22"
PI_ROOT = Path.home() / ".pi/agent/sessions"


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def seconds(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()


def purpose(text):
    if re.search(r"\bst\s+(?:-P\s+\S+\s+)?check\b", text):
        return "required_acceptance"
    if "git diff" in text or "git status" in text:
        return "diff_scope_verification"
    return "source_work"


def union(intervals):
    total = 0.0
    end = None
    for start, stop in sorted(intervals):
        if end is None or start > end:
            total += stop - start
        else:
            total += max(0, stop - end)
        end = max(end or stop, stop)
    return total


def cost(usage):
    return (usage["uncached_input"] * RATES["uncached_input"]
            + usage["cache_read_input"] * RATES["cached_read"]
            + usage["cache_write_input"] * RATES["cache_write_30m"]
            + (usage["visible_output"] + usage["reasoning_output"]) * RATES["output_including_reasoning"]) / 1e6


def disjoint(uncached, cached, write, output, reasoning):
    assert min(uncached, cached, write, output - reasoning, reasoning) >= 0
    return dict(uncached_input=uncached, cache_read_input=cached, cache_write_input=write,
                visible_output=output - reasoning, reasoning_output=reasoning)


def codex(path):
    items = read_lines(path)
    tokens, seen = [], set()
    calls, intervals, admin = {}, [], []
    model_contexts = []
    compactions = 0
    for row in items:
        payload = row.get("payload", {})
        if row["type"] == "turn_context":
            model_contexts.append({"model": payload.get("model"), "effort": payload.get("effort"), "approval_policy": payload.get("approval_policy"), "sandbox_policy": payload.get("sandbox_policy")})
        if row["type"] == "event_msg" and payload.get("type") == "token_count" and payload.get("info"):
            info = payload["info"]
            key = json.dumps(info["total_token_usage"], sort_keys=True)
            if key not in seen:
                seen.add(key)
                tokens.append(info)
        if row["type"] == "compacted" or payload.get("type") == "context_compacted":
            compactions += 1
        kind = payload.get("type", "")
        if row["type"] == "response_item" and kind in {"function_call", "custom_tool_call"}:
            text = payload.get("arguments", payload.get("input", ""))
            calls[payload["call_id"]] = (seconds(row["timestamp"]), purpose(text))
        if row["type"] == "response_item" and kind in {"function_call_output", "custom_tool_call_output"}:
            call = calls.get(payload.get("call_id"))
            if call:
                interval = (call[0], seconds(row["timestamp"]))
                intervals.append(interval)
                if call[1] != "source_work":
                    admin.append(interval)
    if not tokens:
        return {"native_session": path.stem, "usage_known": False}
    total = tokens[-1]["total_token_usage"]
    usage = disjoint(total["input_tokens"] - total.get("cached_input_tokens", 0) - total.get("cache_write_input_tokens", 0), total.get("cached_input_tokens", 0), total.get("cache_write_input_tokens", 0), total["output_tokens"], total.get("reasoning_output_tokens", 0))
    percall = [x["last_token_usage"] for x in tokens]
    # No summing cumulative counters. The disjoint per-call series must agree.
    assert sum(x["input_tokens"] for x in percall) == total["input_tokens"]
    assert sum(x["output_tokens"] for x in percall) == total["output_tokens"]
    first = percall[0]
    starts = [seconds(r["timestamp"]) for r in items if r["type"] == "turn_context"]
    ends = [seconds(r["timestamp"]) for r in items if r["type"] == "event_msg" and r["payload"].get("type") == "task_complete"]
    return {"native_session_id": next(r["payload"]["id"] for r in items if r["type"] == "session_meta"), "native_version": next(r["payload"].get("cli_version") for r in items if r["type"] == "session_meta"), "model_settings": model_contexts, "usage_known": True, "disjoint_tokens": usage, "first_call_input_including_cache": first["input_tokens"], "first_call_cached_input": first.get("cached_input_tokens", 0), "model_calls": len(tokens), "compactions": compactions, "api_equivalent_usd": cost(usage), "tool_calls": len(intervals), "tool_seconds_sum": sum(b-a for a,b in intervals), "tool_seconds_union": union(intervals), "verification_tool_seconds_union": union(admin), "active_seconds": (max(ends)-min(starts)) if starts and ends else None}


def pi(root):
    rows = read_lines(root / "pi-receipts.jsonl")
    responses = [r for r in rows if r["type"] == "response"]
    requests = [r for r in rows if r["type"] == "request"]
    session = next(r for r in rows if r["type"] == "session")
    contexts = [r for r in rows if r["type"] == "context"]
    native_dir = PI_ROOT / ("--" + str(root).strip("/").replace("/", "-") + "--")
    transcript = next(native_dir.glob("*" + session["session_id"] + ".jsonl"))
    categories = {}
    for row in read_lines(transcript):
        for block in row.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "toolCall":
                categories[block["id"]] = purpose(json.dumps(block.get("arguments", {}))) if block.get("name") == "bash" else "source_work"
    starts, intervals, admin = {}, [], []
    for row in rows:
        if row["type"] == "tool_start":
            starts[row["id"]] = row["at"] / 1000
        if row["type"] == "tool_end" and row["id"] in starts:
            interval = (starts[row["id"]], row["at"] / 1000)
            intervals.append(interval)
            if categories.get(row["id"]) in {"required_acceptance", "diff_scope_verification"}:
                admin.append(interval)
    native = [r["usage"] for r in responses]
    usage = disjoint(sum(u["input"] for u in native), sum(u["cacheRead"] for u in native), sum(u["cacheWrite"] for u in native), sum(u["output"] for u in native), sum(u.get("reasoning", 0) for u in native))
    assert all(u["input"] + u["cacheRead"] + u["cacheWrite"] + u["output"] == u["totalTokens"] for u in native)
    settlements = [r["at"] for r in rows if r["type"] == "settled"]
    return {"native_session_id": session["session_id"], "native_version": "1.4.0", "model_settings": {k: session[k] for k in ["model", "provider", "thinking", "tools"]}, "usage_known": True, "disjoint_tokens": usage, "first_call_input_including_cache": native[0]["input"] + native[0]["cacheRead"] + native[0]["cacheWrite"], "first_call_cached_input": native[0]["cacheRead"], "model_calls": len(native), "compactions": sum(r["type"] == "compaction" for r in rows), "api_equivalent_usd": cost(usage), "native_reported_cost_usd": sum(u.get("cost", {}).get("total", 0) for u in native), "tool_calls": len(intervals), "tool_seconds_sum": sum(b-a for a,b in intervals), "tool_seconds_union": union(intervals), "verification_tool_seconds_union": union(admin), "active_seconds": (responses[-1]["at"] - requests[0]["at"]) / 1000, "whole_seconds": (max(settlements)/1000 - json.loads((root/"attempt.json").read_text())["started"]) if settlements else None, "transport_verified": bool(requests) and all(r.get("system_exactly_expected") and r.get("replaced_system_fields") == 1 for r in requests), "requests_verified": sum(bool(r.get("system_exactly_expected")) for r in requests), "requests_observed": len(requests), "context_receipts": contexts}


def acceptance(name):
    path = BASE / "receipts" / f"{name}-acceptance.log"
    if not path.exists():
        return None
    for line in reversed(path.read_text().splitlines()):
        if line.startswith('{"accepted"'):
            return json.loads(line)
    return None


def main():
    results = []
    for root in sorted((BASE / "runs").iterdir()):
        condition = json.loads((root / "condition.json").read_text())
        if condition["harness"] == "pi":
            if not (root/"pi-receipts.jsonl").exists() or '"type":"settled"' not in (root/"pi-receipts.jsonl").read_text():
                continue
            receipt = pi(root)
        else:
            if not (root/"result.json").exists():
                continue
            run = json.loads((root/"result.json").read_text())
            native_id = next(x["thread_id"] for x in run["events"] if x["type"] == "thread.started")
            native_path = next(CODEX_DAY.glob("*" + native_id + ".jsonl"))
            receipt = codex(native_path)
            receipt["whole_seconds"] = run["whole_seconds"]
            expected = Path(condition["context_payload"]).read_text()
            receipt["exact_developer_payload_copies"] = sum(
                block.get("text") == expected
                for row in read_lines(native_path)
                if row["type"] == "response_item" and row["payload"].get("role") == "developer"
                for block in row["payload"].get("content", [])
            )
            receipt["transport_verified"] = receipt["exact_developer_payload_copies"] == 1
        receipt.update(condition=root.name, harness=condition["harness"], optional_context=condition["optional_context"], acceptance=acceptance(root.name))
        receipt["subject_source_sha256"] = {name: hashlib.sha256(__import__('subprocess').check_output(["git", "-C", str(root), "show", f"HEAD:{name}"])).hexdigest() for name in ["windows.py", "paging.py", "catalog.py", "README.md"]}
        results.append(receipt)
    (BASE / "results.json").write_text(json.dumps(results, indent=2))
    groups = {}
    for row in results:
        key = f"{row['harness']}-{'on' if row['optional_context'] else 'off'}-{'matched' if row['transport_verified'] else 'pilot'}"
        groups.setdefault(key, []).append(row)
    summary = {}
    for key, rows in groups.items():
        accepted = sum(bool(r["acceptance"] and r["acceptance"]["accepted"]) for r in rows)
        summary[key] = {"attempts":len(rows), "accepted":accepted, "total_usd":sum(r["api_equivalent_usd"] for r in rows), "cost_per_accepted_usd":sum(r["api_equivalent_usd"] for r in rows)/accepted if accepted else None}
        for field in ["api_equivalent_usd", "active_seconds", "whole_seconds", "tool_seconds_union", "verification_tool_seconds_union"]:
            values=[r[field] for r in rows if r[field] is not None]
            summary[key][field] = {"mean":statistics.mean(values), "min":min(values), "max":max(values), "sample_sd":statistics.stdev(values) if len(values)>1 else None}
    (BASE / "summary.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    main()
