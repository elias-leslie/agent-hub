"""Freeze public runtime-equivalent previews, with required-byte comparison."""

import hashlib
import json
import subprocess

from prepare import BASE, TASK


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


receipts = {}
required = {}
for arm in ["on", "off"]:
    result = subprocess.run(["st", "agents", "preview", f"harness-trial-20261022-{arm}", "--project", "agent-hub", "--input", TASK, "--json"], check=True, capture_output=True, text=True)
    preview = json.loads(result.stdout)
    (BASE / "private" / f"preview-{arm}.json").write_text(result.stdout)
    (BASE / "private" / f"payload-{arm}.txt").write_text(preview["full_context"])
    required[arm] = {s["source_id"]: digest(s["content"]) for s in preview["sections"] if s["source_kind"].startswith("canonical_") and s["source_kind"] not in {"canonical_reference", "canonical_reference_index", "canonical_project_index", "canonical_tool_capabilities", "canonical_continuity"}}
    receipts[arm] = {"surface": "agent_preview", "transport": "frozen additive preview", "payload_sha256": digest(preview["full_context"]), "payload_bytes": len(preview["full_context"].encode()), "estimated_tokens": preview["full_context_estimated_tokens"], "canonical_context": preview["canonical_context"], "required_section_hashes": required[arm], "selected_reference_uuids": preview["reference_uuids"], "passive_reference_index_uuids": preview["reference_index_uuids"], "guardrail_uuids": preview["guardrail_uuids"], "mandate_uuids": preview["mandate_uuids"]}
assert required["on"] == required["off"], "required context changed"
(BASE / "context-freeze.json").write_text(json.dumps(receipts, indent=2))
print(json.dumps({arm: {k: v for k, v in rec.items() if k in ["payload_sha256", "payload_bytes", "estimated_tokens"]} for arm, rec in receipts.items()}))
