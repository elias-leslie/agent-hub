"""First-turn capture: transcript heads, parts, delivery rows, config steps and the collector hook."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.context_observability import baseline, capture, deliveries, first_turn
from app.services.subscription_accounting import collector

DELIVERED = "## Safety Directive\nFinish the work.\n" + "x" * 800
DELIVERED_HASH = hashlib.sha256(DELIVERED.encode()).hexdigest()
DELIVERY = {
    "delivery_id": "d-1", "est_tokens": 600, "work_role": "implementation", "coordinator": False,
    "blocks": [
        {"scope": "global", "tokens": 300}, {"scope": "project", "tokens": 100}, {"scope": None, "tokens": 100},
    ],
}


def _write(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))
    return path


def _claude_records(*, sid: str = "s1", fp: str = "shape-a", sidechain: bool = False) -> list[dict]:
    return [
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
        {"type": "user", "message": {"role": "user", "content": "Build milestone M1a."}, "cwd": "/srv/workspaces/projects/agent-hub"},
        {"type": "attachment", "attachment": {"type": "skill_listing", "content": "s" * 400}},
        {"type": "attachment", "attachment": {"type": "agent_listing_delta", "addedLines": ["a" * 100, "b" * 100]}},
        {"type": "attachment", "attachment": {"type": "instructions", "files": [
            {"path": "/h/.local/state/agent-hub/context-deliveries/claude_code/p/s/claude-context-1/CLAUDE.md",
             "type": "Project", "content": DELIVERED},
        ]}},
        {"type": "api-request-shape", "shapeHash": fp, "version": "2.1.316",
         "shape": {"system": [{"type": "text", "text": "y" * 1000}], "tools": [{"name": "t", "d": "z" * 600}]}},
        {"type": "api-request-blob", "x": "{big}"},
        {"type": "assistant", "version": "2.1.316", "timestamp": "2026-11-01T12:00:00Z", "isSidechain": sidechain,
         "message": {"id": "m1", "model": "claude-opus-5-5", "usage": {
             "input_tokens": 2, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 3000, "output_tokens": 5}}},
    ]


def test_claude_head_reads_the_first_call_the_shape_the_listings_and_the_delivered_instructions(tmp_path: Path) -> None:
    raw = first_turn.read_claude_head(_write(tmp_path / "s1.jsonl", _claude_records()))

    assert raw is not None
    assert (raw["total"], raw["model"], raw["version"], raw["fp"]) == (4002, "claude-opus-5-5", "2.1.316", "shape-a")
    assert (raw["sys_chars"], raw["listing_chars"], raw["brief_chars"]) == (1000, 600, 20)
    assert raw["tools_chars"] == len(json.dumps([{"name": "t", "d": "z" * 600}], separators=(",", ":")))
    assert [f["sha"] for f in raw["inst_files"]] == [DELIVERED_HASH]


def test_claude_head_is_none_until_the_first_model_call(tmp_path: Path) -> None:
    assert first_turn.read_claude_head(_write(tmp_path / "s.jsonl", _claude_records()[:5])) is None


def test_parts_split_the_harness_remainder_by_character_weight_and_keep_the_total_exact(tmp_path: Path) -> None:
    raw = first_turn.read_claude_head(_write(tmp_path / "s1.jsonl", _claude_records()))

    parts = first_turn.compute_parts(raw, delivery=DELIVERY, launch_mode="project")

    assert parts["total"] == {"tokens": 4002, "method": "exact"}
    assert parts["ours"] == {"tokens": 600, "method": "estimate"}
    assert parts["brief"]["tokens"] == 5
    assert parts["harness"]["tokens"] == 4002 - 600 - 5
    split = [parts[n]["tokens"] for n in first_turn.HARNESS_PART_NAMES]
    assert sum(split) == parts["harness"]["tokens"] and split[0] > split[1] > split[2]
    assert [parts[n]["tokens"] for n in ("ah_global", "ah_role", "ah_project")] == [480, 0, 120]


def test_unbound_project_launch_has_unknown_ours_but_a_blank_launch_without_delivery_is_exactly_zero(tmp_path: Path) -> None:
    records = [r for r in _claude_records() if r.get("attachment", {}).get("type") != "instructions"]
    raw = first_turn.read_claude_head(_write(tmp_path / "s1.jsonl", records))

    parts = first_turn.compute_parts(raw, delivery=None, launch_mode="blank")

    assert parts["ours"] == {"tokens": 0, "method": "exact"}
    assert parts["harness"]["tokens"] == 4002 - 5

    codex = {"harness": "codex", "total": 5000, "brief_chars": 40, "dev_texts": ["d" * 200], "base_chars": 400,
             "env_chars": 0, "tools_chars": 400, "skills_chars": 200}
    unbound = first_turn.compute_parts(codex, delivery=None, launch_mode="project")
    assert unbound["ours"] == {"tokens": None, "method": "unknown"}
    assert unbound["harness"]["tokens"] is None  # unknown is not zero


def test_scope_split_adds_up_to_the_delivery_total() -> None:
    blocks = [{"scope": "global", "tokens": 7}, {"scope": "project", "tokens": 7}, {"scope": "role", "tokens": 7}]

    split = first_turn.split_scope_tokens(blocks, 100)

    assert sum(split.values()) == 100 and set(split) == {"ah_global", "ah_role", "ah_project"}


def test_launch_mode_and_identity(tmp_path: Path) -> None:
    sub = tmp_path / "proj" / "sess-1" / "subagents" / "agent-abc.jsonl"
    sub.parent.mkdir(parents=True)
    sub.with_suffix(".meta.json").write_text(json.dumps({"agentType": "Explore"}))

    assert first_turn.claude_identity(sub) == ("sess-1", "abc")
    assert first_turn.launch_mode_for(sub, None, first_turn.claude_agent_type(sub)) == "subagent:Explore"
    assert first_turn.launch_mode_for(tmp_path / "-srv-blank-slate" / "s.jsonl", None, None) == "blank"
    assert first_turn.launch_mode_for(tmp_path / "p" / "s.jsonl", "/srv/x", None) == "project"
    assert first_turn.launch_mode_for(tmp_path / "p" / "s.jsonl", "/srv/x", None, "codex_exec") == "exec"
    assert first_turn.launch_mode_for(tmp_path / "p" / "s.jsonl", "/srv/x", None, "codex-tui") == "project"


def _codex_records(*, root: str = "root-1", own: str = "root-1", delivered: str | None = DELIVERED) -> list[dict]:
    dev = [{"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "You are Codex. " + "b" * 300}]},
           {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "<skills_instructions>" + "k" * 100}]}]
    if delivered:
        dev.append({"type": "message", "role": "developer", "content": [
            {"type": "input_text", "text": delivered + "\n<collaboration_mode>" + "c" * 50}]})
    return [
        {"type": "session_meta", "payload": {"id": own, "session_id": root, "cwd": "/srv/workspaces/projects/neri",
                                              "cli_version": "0.164.0", "timestamp": "2026-11-01T12:00:00Z"}},
        {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        {"type": "response_item", "payload": {"type": "additional_tools", "tools": [{"name": "exec", "d": "t" * 90}]}},
        *({"type": "response_item", "payload": p} for p in dev),
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>" + "e" * 40}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Reply OK."}]}},
        {"type": "event_msg", "timestamp": "2026-11-01T12:00:05Z", "payload": {
            "type": "token_count", "info": {"last_token_usage": {"input_tokens": 5000, "cached_input_tokens": 0, "output_tokens": 3}}}},
    ]


def test_codex_head_keeps_developer_texts_for_binding_and_counts_the_rest(tmp_path: Path) -> None:
    raw = first_turn.read_codex_head(_write(tmp_path / "r.jsonl", _codex_records()))

    assert raw is not None
    assert (raw["total"], raw["version"], raw["model"], raw["sid"], raw["aid"]) == (5000, "0.164.0", "gpt-6.1-sol", "root-1", "")
    assert (raw["brief_chars"], raw["skills_chars"]) == (9, 121) and raw["base_chars"] == 315
    assert [len(t) for t in raw["dev_texts"]] == [len(DELIVERED) + len("\n<collaboration_mode>" + "c" * 50)]
    assert raw["dev_texts"][0].startswith(DELIVERED) and len(raw["fp"]) == 16


def test_codex_parts_separate_the_delivery_from_the_rest_of_its_developer_message(tmp_path: Path) -> None:
    raw = first_turn.read_codex_head(_write(tmp_path / "r.jsonl", _codex_records()))

    parts = first_turn.compute_parts(raw, delivery=DELIVERY, launch_mode="project", ah_chars_in_text=len(DELIVERED))

    assert parts["ours"]["tokens"] == 600 and parts["chars"]["ah"] == len(DELIVERED)
    assert parts["chars"]["harness_core"] == 315 + len("<environment_context>" + "e" * 40) + len("\n<collaboration_mode>" + "c" * 50)


def test_codex_child_threads_have_no_first_turn_of_their_own(tmp_path: Path) -> None:
    from app.services.context_observability import capture

    child = _write(tmp_path / "c.jsonl", _codex_records(root="root-1", own="child-1"))
    root = _write(tmp_path / "r.jsonl", _codex_records())

    assert capture.head_for_codex(child) is None
    head = capture.head_for_codex(root)
    assert head is not None and (head.session_id, head.agent_id, head.launch_mode) == ("root-1", "", "project")


def test_scan_attaches_one_head_per_session_including_subagents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_CODEX_SESSIONS", str(tmp_path / "codex"))
    monkeypatch.setenv("AGENT_HUB_CLAUDE_PROJECTS", str(tmp_path / "claude"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    proj = tmp_path / "claude" / "-srv-workspaces-projects-agent-hub"
    main = _claude_records()
    main[-1]["requestId"] = "r1"
    extra = dict(main[-1], requestId="r2", message=dict(main[-1]["message"], id="m2"))
    _write(proj / "s1.jsonl", [*main, extra])
    sub = _claude_records(sidechain=True)
    sub[-1]["requestId"] = "r3"
    sub[-1]["message"] = dict(sub[-1]["message"], id="m3")
    _write(proj / "s1" / "subagents" / "agent-xyz.jsonl", sub)
    (proj / "s1" / "subagents" / "agent-xyz.meta.json").write_text(json.dumps({"agentType": "code-reviewer"}))
    now = datetime(2026, 11, 1, 13, tzinfo=UTC).timestamp()

    result = collector.scan({}, now=now)

    heads = {(h.provider, h.session_id, h.agent_id): h for h in result.heads}
    assert set(heads) == {("claude", "s1", ""), ("claude", "s1", "xyz")}
    assert heads[("claude", "s1", "xyz")].launch_mode == "subagent:code-reviewer"
    assert heads[("claude", "s1", "")].raw["total"] == 4002


def _fixture_contract(**over: object) -> dict:
    contract = {
        "schema_version": "agent-hub.context.v1", "delivery_id": "d-9", "payload_hash": "h" * 64, "status": "ok",
        "generated_at": "2026-11-01T12:00:00+00:00", "estimated_tokens": 500, "rendered": "r" * 2000,
        "metadata": {"consumer_surface": "claude_code", "consumer_profile": "agent_startup", "project_id": "agent-hub",
                     "consumer_tags": ["aico-coordinator", "work-role:coordinator"], "session_id": "sess",
                     "client_metadata": {"remote_host": "vm201"}},
        "blocks": [
            {"block_id": "prompt:safety", "kind": "prompt", "estimated_tokens": 300,
             "provenance": {"source_type": "prompt", "source_id": "safety", "source_revision": "r3", "scope": "global"}},
            {"block_id": "tool-capabilities:p", "kind": "tool_capabilities", "estimated_tokens": 200,
             "provenance": {"source_type": "computed", "source_id": "tc", "source_revision": "x", "scope": "project"}},
        ],
    }
    contract.update(over)
    return contract


def test_delivery_row_values_carry_role_scope_tokens_host_and_block_revisions() -> None:
    values = deliveries.values_from_contract(_fixture_contract(), source="api")

    assert values is not None
    assert (values["work_role"], values["coordinator"], values["host"], values["rendered_chars"]) == ("coordinator", True, "vm201", 2000)
    assert values["by_scope"] == {"global": 300, "project": 200}
    assert values["blocks"][0] == {
        "block_id": "prompt:safety", "kind": "prompt", "source_type": "prompt", "source_id": "safety", "revision": "r3",
        "scope": "global", "tokens": 300,
    }


def test_a_failed_or_incomplete_delivery_is_not_a_row() -> None:
    assert deliveries.values_from_contract(_fixture_contract(status="failed"), source="api") is None
    assert deliveries.values_from_contract(_fixture_contract(failure={"operation": "x"}), source="api") is None
    assert deliveries.values_from_contract(_fixture_contract(payload_hash=""), source="api") is None


def test_roles_from_tags() -> None:
    assert deliveries.role_from_tags(["work-role:hunting"]) == ("hunting", False)
    assert deliveries.role_from_tags(["aico-coordinator"]) == ("coordinator", True)
    assert deliveries.role_from_tags([]) == (None, False)


def test_contract_files_import_by_delivery_id_and_skip_other_schemas(tmp_path: Path) -> None:
    root = tmp_path / "deliveries"
    (root / "claude_code" / "agent-hub" / "sess").mkdir(parents=True)
    (root / "claude_code" / "agent-hub" / "sess" / "a.json").write_text(json.dumps(_fixture_contract()))
    (root / "claude_code" / "agent-hub" / "sess" / "b.json").write_text(json.dumps(_fixture_contract(schema_version="other")))
    (root / "claude_code" / "agent-hub" / "sess" / "c.json").write_text(json.dumps(_fixture_contract(generated_at="2026-01-01T00:00:00+00:00")))

    rows = deliveries.import_contract_values([root], since=datetime(2026, 10, 1, tzinfo=UTC))

    assert [r["delivery_id"] for r in rows] == ["d-9"] and rows[0]["source"] == "file"


async def test_record_flag_stores_an_ok_delivery_and_a_preview_stores_nothing() -> None:
    from app.services import runtime_context

    ok = SimpleNamespace(status="ok")
    failed = SimpleNamespace(status="failed")
    with (
        patch.object(runtime_context, "_build_canonical_context_delivery", new=AsyncMock(side_effect=[ok, ok, failed])),
        patch("app.services.context_observability.deliveries.record_delivery", new=AsyncMock()) as record,
    ):
        await runtime_context.build_canonical_context_delivery(None, None, record="api")
        await runtime_context.build_canonical_context_delivery(None, None)
        await runtime_context.build_canonical_context_delivery(None, None, record="host")

    record.assert_awaited_once_with(ok, source="api")


def _turn(at: datetime, total: int, fp: str, version: str = "2.1.316", role: str = "implementation") -> baseline.FirstTurn:
    return baseline.FirstTurn(
        provider="claude", session_id=f"s{at.timestamp()}", agent_id="", harness="claude", version=version, role=role,
        coordinator=False, launch_mode="project", model="m", at=at, total=total, harness_tokens=None, ours_tokens=None,
        brief_tokens=None, config_fp=fp, delivery_id=None,
    )


def test_config_step_names_the_new_shape_and_says_the_version_did_not_change() -> None:
    base = datetime(2026, 11, 1, 10, tzinfo=UTC)
    rows = [_turn(base + timedelta(minutes=10 * i), 48_300 + i, "old") for i in range(5)]
    rows += [_turn(datetime(2026, 11, 1, 14, 53, tzinfo=UTC) + timedelta(minutes=i), 24_300, "new") for i in range(3)]

    (step,) = baseline.config_steps(rows)

    assert (step["from_fp"], step["config_fp"], step["same_version"]) == ("old", "new", True)
    assert (step["median_before"], step["median_after"], step["delta"]) == (48_302, 24_300, 24_300 - 48_302)
    assert step["at"] == datetime(2026, 11, 1, 14, 53, tzinfo=UTC)


def test_medians_ignore_unknown_values_and_are_none_without_any() -> None:
    assert baseline.med([None, 3, 1, 2, None]) == 2 and baseline.med([None]) is None
    assert baseline.med([4, 1, 3, 2]) == 3  # upper median, as the DESIGN measurement scripts took it


def test_a_malformed_contract_or_binding_file_is_skipped_and_the_rest_still_import(tmp_path: Path) -> None:
    root = tmp_path / "deliveries"
    sess = root / "claude_code" / "agent-hub" / "sess"
    (sess / "bindings").mkdir(parents=True)
    (sess / "bad.json").write_text(json.dumps(_fixture_contract(metadata=["not", "a", "dict"])))
    (sess / "worse.json").write_text(json.dumps(_fixture_contract(delivery_id="d-8", estimated_tokens="many")))
    (sess / "good.json").write_text(json.dumps(_fixture_contract()))
    good = {"schema_version": deliveries.BINDING_SCHEMA, "bound_at": "2026-11-01T12:00:00+00:00",
            "canonical_delivery_id": "d-9", "native_session_id": "n1", "native_subagent_id": None, "consumer_surface": "claude_code"}
    (sess / "bindings" / "a.json").write_text(json.dumps(good))
    (sess / "bindings" / "b.json").write_text(json.dumps([1, 2]))

    rows = deliveries.import_contract_values([root], since=datetime(2026, 10, 1, tzinfo=UTC))
    bindings = deliveries.load_bindings([root], since=datetime(2026, 10, 1, tzinfo=UTC))

    assert [r["delivery_id"] for r in rows] == ["d-9"]
    assert set(bindings) == {("claude_code", "n1", "")}


def test_the_binding_in_effect_at_the_first_call_wins() -> None:
    at = datetime(2026, 11, 1, 12, tzinfo=UTC)
    key = ("claude_code", "n1", "")
    bindings = {key: [(at - timedelta(minutes=3), "early", None), (at - timedelta(seconds=10), "late", "/c.json"), (at + timedelta(minutes=9), "after", None)]}

    assert deliveries.pick_binding(bindings, key, at) == ("late", "/c.json")
    assert deliveries.pick_binding(bindings, key, at - timedelta(minutes=30)) == ("early", None)
    assert deliveries.pick_binding(bindings, ("claude_code", "other", ""), at) is None


def test_every_real_delivery_site_passes_its_record_name_and_previews_pass_none() -> None:
    import ast

    app = Path(__file__).resolve().parents[2] / "app"
    expected = {
        "api/runtime_context.py": "api", "api/host_context.py": "host", "cli/runtime_context.py": "cli",
        "services/memory/context_injector_ops.py": "agent", "services/workflow_runs/engine.py": "workflow",
    }
    found: dict[str, list[str | None]] = {}
    for path in app.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "build_canonical_context_delivery":
                names = [kw.value.value for kw in node.keywords if kw.arg == "record" and isinstance(kw.value, ast.Constant)]
                found.setdefault(str(path.relative_to(app)), []).append(names[0] if names else None)

    recorded = {rel: names for rel, names in found.items() if any(names)}
    assert recorded == {rel: [name] for rel, name in expected.items()}
    assert all(n is None for rel, names in found.items() if rel not in expected for n in names)


def test_a_failed_backfill_waits_for_its_retry_time() -> None:
    now = datetime(2026, 11, 1, 12, tzinfo=UTC)
    later = (now + timedelta(minutes=30)).isoformat()
    earlier = (now - timedelta(minutes=1)).isoformat()
    state = collector.CONTEXT_BACKFILL_STATE

    assert collector._context_backfill_waiting({state: (0, {"retry_after": later})}, now)
    assert not collector._context_backfill_waiting({state: (0, {"retry_after": earlier})}, now)
    assert not collector._context_backfill_waiting({}, now)
    assert not collector._context_backfill_done({state: (0, {"retry_after": later})})


def test_a_backfill_where_sessions_failed_is_retried_not_marked_done() -> None:
    assert not capture.backfill_failed({"sessions_read": 100, "sessions_updated": 90, "sessions_failed": 10, "stages_failed": 0})
    assert capture.backfill_failed({"sessions_read": 100, "sessions_updated": 0, "sessions_failed": 100, "stages_failed": 0})
    assert capture.backfill_failed({"sessions_read": 10, "sessions_updated": 10, "sessions_failed": 0, "pi_read": 5, "pi_updated": 0})
    assert capture.backfill_failed({"sessions_read": 10, "sessions_updated": 10, "sessions_failed": 0, "stages_failed": 1})
    assert not capture.backfill_failed({"sessions_read": 10, "sessions_updated": 4, "sessions_failed": 0, "sessions_skipped": 6})  # no ledger row yet


async def test_the_collector_stores_retry_after_not_the_version_when_the_backfill_mostly_failed() -> None:
    stored: list[dict] = []

    async def store(_db, state):
        stored.append(state)

    summary = {"sessions_read": 100, "sessions_updated": 0, "sessions_failed": 100, "stages_failed": 0}
    with patch.object(collector.context_capture, "backfill", AsyncMock(return_value=summary)), \
            patch.object(collector, "_store_context_backfill_state", store):
        await collector._backfill_context_once(AsyncMock(), {})

    assert len(stored) == 1 and "retry_after" in stored[0] and "version" not in stored[0]


def test_headless_codex_exec_coordinator_runs_are_their_own_cell() -> None:
    def row(mode: str, role: str) -> baseline.FirstTurn:
        return baseline.FirstTurn("codex", "s", "", "codex", None, role, role == "coordinator", mode, "m", datetime(2026, 11, 1, tzinfo=UTC), 1, None, None, None, None, None)

    assert row("project", "coordinator").cell == "coordinator"
    assert row("exec", "coordinator").cell == "exec:coordinator"
    assert row("exec", "implementation").cell == "implementation"
