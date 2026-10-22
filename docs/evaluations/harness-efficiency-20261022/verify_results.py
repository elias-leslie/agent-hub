"""Focused deterministic checks for disjoint pricing and trial receipts."""

import json
import tempfile
from pathlib import Path

from collect import BASE, codex, cost, disjoint

assert cost(disjoint(1000, 4000, 0, 100, 20)) == 0.0034
assert cost(disjoint(1000, 4000, 0, 100, 0)) == 0.0034
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "native.jsonl"
    usage = {"input_tokens": 5000, "cached_input_tokens": 4000,
             "cache_write_input_tokens": 0, "output_tokens": 100,
             "reasoning_output_tokens": 20}
    token = {"type": "event_msg", "timestamp": "2026-10-22T18:00:02Z",
             "payload": {"type": "token_count", "info": {"total_token_usage": usage, "last_token_usage": usage}}}
    rows = [{"type": "session_meta", "payload": {"id": "synthetic", "cli_version": "fixture"}},
            {"type": "turn_context", "timestamp": "2026-10-22T18:00:00Z", "payload": {}},
            token, token,
            {"type": "event_msg", "timestamp": "2026-10-22T18:00:03Z", "payload": {"type": "task_complete"}}]
    path.write_text("\n".join(json.dumps(row) for row in rows))
    result = codex(path)
    assert result["model_calls"] == 1
    assert result["api_equivalent_usd"] == 0.0034
    assert result["disjoint_tokens"]["visible_output"] == 80
    assert result["disjoint_tokens"]["uncached_input"] == 1000

rows = json.loads((BASE / "results.json").read_text())
assert len(rows) == 13
assert sum(row["model_calls"] for row in rows) == 89
assert all(row["acceptance"]["accepted"] and row["acceptance"]["passed"] == 16 for row in rows)
assert len({json.dumps(row["subject_source_sha256"], sort_keys=True) for row in rows}) == 1
assert all(row["disjoint_tokens"]["cache_write_input"] == 0 for row in rows)
assert all(row["compactions"] == 0 for row in rows)
for row in rows:
    if row["harness"] == "pi":
        assert abs(row["native_reported_cost_usd"] - row["api_equivalent_usd"]) < 1e-10
        if row["transport_verified"]:
            assert row["requests_verified"] == row["requests_observed"]
    else:
        assert row["exact_developer_payload_copies"] == 1
        assert all(x["model"] == "gpt-6.1-sol" and x["effort"] == "xhigh" for x in row["model_settings"])
context = json.loads((BASE / "context-freeze.json").read_text())
assert context["on"]["required_section_hashes"] == context["off"]["required_section_hashes"]
assert len(context["on"]["required_section_hashes"]) == 21
assert context["on"]["selected_reference_uuids"] == context["off"]["selected_reference_uuids"] == []
assert context["on"]["passive_reference_index_uuids"] == context["off"]["passive_reference_index_uuids"] == []
print("PASS: 13 accepted native outcomes, 89 calls, identical fixture starts; disjoint pricing, duplicate-counter handling, required-byte integrity and native payload receipts verified.")
