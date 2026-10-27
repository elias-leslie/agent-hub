"""Codex and Pi step executors against recorded event streams, replayed by a stub harness binary."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.llm.utils.outcomes import ProviderOutcome
from app.services.workflow_runs.executor_codex import CodexExecutor
from app.services.workflow_runs.executor_common import (
    FALLBACK_NOTE,
    classify_failure,
    load_defaults,
)
from app.services.workflow_runs.executor_pi import PiExecutor
from app.services.workflow_runs.executors import get_executor
from app.services.workflow_runs.packet import GitState, build_packet

FIXTURES = Path(__file__).parents[2] / "fixtures" / "workflow_executors"
CODEX_MODEL, DAYBREAK_MODEL, CLAUDE_MODEL = "codex/gpt-6.1-sol", "codex/gpt-5.6-sol-daybreak-blue", "claude-sonnet-5-5"
CATALOG = {
    CODEX_MODEL: SimpleNamespace(
        provider="codex",
        access_programs=None,
        capabilities=SimpleNamespace(supports_xhigh=True, thinking_level_map={"minimal": "low"}),
    ),
    DAYBREAK_MODEL: SimpleNamespace(
        provider="codex",
        access_programs={"cyber": "daybreak_blue"},
        capabilities=SimpleNamespace(supports_xhigh=False, thinking_level_map=None),
    ),
    CLAUDE_MODEL: SimpleNamespace(
        provider="claude", access_programs=None, capabilities=SimpleNamespace(supports_xhigh=True, thinking_level_map=None)
    ),
}


def packet(context: str = "", **extra):
    built = build_packet(
        run_goal="goal",
        step_key="build",
        instructions="Create hello.txt.",
        acceptance=[],
        git=GitState(),
        prior_steps=[],
        run_dir="/run",
        context_window=100000,
        budget_fraction=0.5,
        context=context,
    )
    for key, value in extra.items():
        object.__setattr__(built, key, value)
    return built


def stub(tmp_path: Path, fixture: str, *, exit_code: int = 0, wait_for_prompt: bool = False) -> tuple[Path, Path]:
    """A harness binary that records argv and stdin, then replays a recorded stream."""

    log = tmp_path / "argv.json"
    script = tmp_path / "harness"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"stdin = ''\n"
        f"if {wait_for_prompt!r}:\n"
        "    for line in sys.stdin:\n"
        "        stdin += line\n"
        "        if '\"prompt\"' in line and '\"type\": \"prompt\"' in line:\n"
        "            break\n"
        "else:\n"
        "    stdin = sys.stdin.read()\n"
        f"open({str(log)!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], 'stdin': stdin}}))\n"
        f"sys.stdout.write(open({str(FIXTURES / fixture)!r}).read())\n"
        "sys.stdout.flush()\n"
        + ("for _ in sys.stdin:\n    pass\n" if wait_for_prompt else "")
        + f"sys.exit({exit_code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, log


def executor(kind: str, binary: Path):
    defaults = load_defaults()
    defaults[kind]["binary"] = str(binary)
    cls = CodexExecutor if kind == "codex" else PiExecutor
    return cls(defaults, model_lookup=CATALOG.get)


async def run(ex, model: str, tmp_path: Path, **kwargs):
    events: list[dict] = []

    async def on_event(event):
        events.append(dict(event))

    worktree = tmp_path / "worktree"
    worktree.mkdir(exist_ok=True)
    result = await ex.run(kwargs.pop("packet", None) or packet(), model, worktree, tmp_path / "run", on_event)
    return result, events


def test_executors_register_under_their_kinds():
    assert isinstance(get_executor("codex"), CodexExecutor)
    assert isinstance(get_executor("pi"), PiExecutor)


# --- codex -------------------------------------------------------------------------------------------


@pytest.fixture
def codex_home(tmp_path, monkeypatch):
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def write_rollout(home: Path, thread_id: str, *records: dict) -> Path:
    path = home / "sessions" / "2026" / "10" / "27" / f"rollout-2026-10-27T00-00-00-{thread_id}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


async def test_codex_completed_run_command_usage_and_fallback_handoff(tmp_path, codex_home):
    thread = "01a17faf-5736-7cc0-b39e-7ea0b0da7df6"
    rollout = write_rollout(
        codex_home, thread, {"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": "high"}}
    )
    binary, log = stub(tmp_path, "codex_exec_completed.jsonl")
    result, events = await run(executor("codex", binary), CODEX_MODEL, tmp_path, packet=packet(thinking_level="xhigh"))

    seen = json.loads(log.read_text())
    argv = seen["argv"]
    assert argv[:2] == ["exec", "--json"]
    assert argv[argv.index("--model") + 1] == "gpt-6.1-sol"
    assert argv[argv.index("--cyber-access-program") + 1] == "standard"
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert 'approval_policy="never"' in argv
    assert 'model_reasoning_effort="xhigh"' in argv
    assert argv[argv.index("-C") + 1] == str(tmp_path / "worktree") and argv[-1] == "-"
    assert "Create hello.txt." in seen["stdin"]

    assert result.status == "completed" and result.outcome is None
    assert result.served_models == ["gpt-6.1-sol"]
    assert result.native_session_id == thread and result.transcript_path == str(rollout)
    # input 35895 includes 24960 cached: the counters stay disjoint.
    assert result.usage["input_tokens"] == 35895 - 24960
    assert result.usage["cache_read_tokens"] == 24960 and result.usage["output_tokens"] == 57
    assert result.handoff["summary"] == "Created hello.txt containing hi."
    assert FALLBACK_NOTE in result.handoff["decisions"]
    assert result.progress[-1] == "Created hello.txt containing hi."
    assert any(item.startswith("$ /bin/bash -lc") for item in result.progress)
    assert [e["event"] for e in events][:2] == ["thread.started", "turn.started"]


async def test_codex_prefers_the_packet_handoff_block_and_passes_context(tmp_path, codex_home):
    config = codex_home / "config.toml"
    config.write_text('developer_instructions = "user rules"\n')
    final = {"type": "item.completed", "item": {"type": "agent_message", "text": "done\n```handoff\n" + json.dumps(
        {"summary": "Wrote it", "decisions": ["d"], "files": ["hello.txt"], "open_questions": []}) + "\n```"}}
    fixture = tmp_path / "block.jsonl"
    fixture.write_text(
        json.dumps({"type": "thread.started", "thread_id": "t1"}) + "\n" + json.dumps(final) + "\n"
        + json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 2}}) + "\n"
    )
    binary, log = stub(tmp_path, str(fixture))
    result, _ = await run(executor("codex", binary), CODEX_MODEL, tmp_path, packet=packet(context="CANON"))
    assert result.handoff == {"summary": "Wrote it", "decisions": ["d"], "files": ["hello.txt"], "open_questions": []}
    argv = json.loads(log.read_text())["argv"]
    instructions = json.loads(next(a for a in argv if a.startswith("developer_instructions=")).split("=", 1)[1])
    assert instructions == "user rules\n\nCANON"


async def test_codex_daybreak_model_requests_its_catalog_program(tmp_path, codex_home):
    binary, log = stub(tmp_path, "codex_exec_completed.jsonl")
    await run(executor("codex", binary), DAYBREAK_MODEL, tmp_path)
    argv = json.loads(log.read_text())["argv"]
    assert argv[argv.index("--cyber-access-program") + 1] == "daybreak_blue"
    assert 'model_reasoning_effort="high"' in argv  # no agent level: the data default, clamped for xhigh-less models


async def test_codex_refusal_uses_the_rollout_error_code_and_keeps_earlier_progress(tmp_path, codex_home):
    write_rollout(
        codex_home,
        "thread-refused",
        {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        {"type": "event_msg", "payload": {"type": "task_complete", "error": {"message": "flagged", "codex_error_info": "cyber_policy"}}},
    )
    binary, _ = stub(tmp_path, "codex_exec_refused.jsonl", exit_code=1)
    result, _ = await run(executor("codex", binary), CODEX_MODEL, tmp_path)
    assert result.status == "failed" and result.handoff is None
    assert result.outcome is not None
    assert result.outcome.kind == "refused" and result.outcome.category == "cyber"
    assert result.outcome.requested_model == CODEX_MODEL
    assert result.progress[0] == "Looking at the target first."
    assert all("flagged for possible" not in item for item in result.progress)


async def test_codex_usage_limit_carries_the_reset(tmp_path, codex_home):
    binary, _ = stub(tmp_path, "codex_exec_usage_limit.jsonl", exit_code=1)
    result, _ = await run(executor("codex", binary), CODEX_MODEL, tmp_path)
    assert result.status == "failed"
    assert result.outcome is not None
    assert result.outcome.kind == "usage_limit" and result.outcome.resets_at == 1793200000
    assert result.outcome.window == "pro"


async def test_codex_reroute_in_the_rollout_is_a_substitution(tmp_path, codex_home):
    write_rollout(
        codex_home,
        "01a17faf-5736-7cc0-b39e-7ea0b0da7df6",
        {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        {"type": "event_msg", "payload": {"type": "model_rerouted", "fromModel": "gpt-6.1-sol", "toModel": "gpt-6", "reason": "high_risk_cyber_activity"}},
        {"type": "turn_context", "payload": {"model": "gpt-6"}},
    )
    binary, _ = stub(tmp_path, "codex_exec_completed.jsonl")
    result, _ = await run(executor("codex", binary), CODEX_MODEL, tmp_path)
    assert result.status == "completed"
    assert result.served_models == ["gpt-6.1-sol", "gpt-6"]
    assert result.outcome == ProviderOutcome("substituted", CODEX_MODEL, served_model="gpt-6", category="cyber", explanation="high_risk_cyber_activity")


async def test_codex_rejects_other_providers_models(tmp_path, codex_home):
    binary, _ = stub(tmp_path, "codex_exec_completed.jsonl")
    result, _ = await run(executor("codex", binary), CLAUDE_MODEL, tmp_path)
    assert result.status == "failed" and result.error.startswith("codex_unsupported")


async def test_codex_exit_without_a_turn_is_a_failure_with_stderr(tmp_path, codex_home):
    script = tmp_path / "harness"
    script.write_text("#!/bin/sh\ncat >/dev/null\necho boom >&2\nexit 3\n")
    script.chmod(0o755)
    result, _ = await run(executor("codex", script), CODEX_MODEL, tmp_path)
    assert result.status == "failed" and "boom" in result.error


# --- pi ----------------------------------------------------------------------------------------------


async def test_pi_completed_session(tmp_path):
    binary, log = stub(tmp_path, "pi_rpc_completed.jsonl", wait_for_prompt=True)
    result, events = await run(executor("pi", binary), CODEX_MODEL, tmp_path, packet=packet(context="CANON"))

    argv = json.loads(log.read_text())["argv"]
    assert argv[:2] == ["--mode", "rpc"]
    assert argv[argv.index("--model") + 1] == "openai/gpt-6.1-sol"
    assert argv[argv.index("--thinking") + 1] == "high"
    assert "--no-extensions" in argv and "--approve" in argv
    context_file = Path(argv[argv.index("--append-system-prompt") + 1])
    assert context_file.read_text() == "CANON"

    assert result.status == "completed" and result.outcome is None
    assert result.served_models == ["gpt-6.1-sol"]
    assert result.native_session_id == "01a17fb3-0951-72db-aa30-454af0df29cc"
    assert result.transcript_path == "/fixture/pi/session.jsonl"
    # Pi reports input without cache; both assistant messages add up.
    assert result.usage["input_tokens"] == 1980 + 225 and result.usage["cache_read_tokens"] == 1792
    assert result.usage["output_tokens"] == 22 + 13
    assert result.handoff["summary"] == "Created `hello.txt` containing `hi`." and FALLBACK_NOTE in result.handoff["decisions"]
    assert result.progress[0].startswith("tool write") and "hello.txt" in result.progress[0]
    assert events and events[-1]["event"] == "agent_settled"


async def test_pi_response_model_switch_is_a_substitution(tmp_path):
    binary, _ = stub(tmp_path, "pi_rpc_model_switch.jsonl", wait_for_prompt=True)
    result, _ = await run(executor("pi", binary), CODEX_MODEL, tmp_path)
    assert result.status == "completed"
    assert result.served_models == ["gpt-6.1-sol", "gpt-6"]
    assert result.outcome == ProviderOutcome("substituted", CODEX_MODEL, served_model="gpt-6")


async def test_pi_error_stop_reason_maps_refusal_and_usage_limit(tmp_path):
    binary, _ = stub(tmp_path, "pi_rpc_refused.jsonl", wait_for_prompt=True)
    refused, _ = await run(executor("pi", binary), CODEX_MODEL, tmp_path)
    assert refused.status == "failed" and refused.handoff is None
    assert refused.outcome is not None and refused.outcome.kind == "refused" and refused.outcome.category == "cyber"
    assert len(refused.progress) == 1 and refused.progress[0].startswith("tool write")

    binary, _ = stub(tmp_path, "pi_rpc_usage_limit.jsonl", wait_for_prompt=True)
    limited, _ = await run(executor("pi", binary), CODEX_MODEL, tmp_path)
    assert limited.outcome is not None and limited.outcome.kind == "usage_limit" and limited.outcome.resets_at == 1793200000


async def test_pi_rejected_prompt_fails_without_waiting(tmp_path):
    binary, _ = stub(tmp_path, "pi_rpc_rejected.jsonl", wait_for_prompt=True)
    result, _ = await run(executor("pi", binary), CODEX_MODEL, tmp_path)
    assert result.status == "failed" and "Model not found" in result.error


async def test_pi_cannot_send_access_programs_or_unmapped_providers(tmp_path):
    binary, _ = stub(tmp_path, "pi_rpc_completed.jsonl", wait_for_prompt=True)
    ex = executor("pi", binary)
    daybreak, _ = await run(ex, DAYBREAK_MODEL, tmp_path)
    assert daybreak.status == "failed" and "access programs" in daybreak.error
    ok, _ = await run(ex, CLAUDE_MODEL, tmp_path)
    assert ok.status == "completed"  # claude maps to Pi's anthropic provider
    ex.settings["provider_for_catalog_provider"] = {}
    unmapped, _ = await run(ex, CLAUDE_MODEL, tmp_path)
    assert unmapped.status == "failed" and "no Pi provider" in unmapped.error


# --- classification ----------------------------------------------------------------------------------


def test_classify_failure_reads_codes_json_bodies_and_plain_limit_text():
    categories = [
        classify_failure("m", "x", "cyber_policy"),
        classify_failure("m", "x", {"cyberPolicy": {}}),
        classify_failure("m", '400 {"error":{"code":"bio_policy"}}'),
    ]
    assert [o.category for o in categories if o] == ["cyber", "cyber", "bio"]
    plain = classify_failure("m", "You've hit your usage limit.")
    assert plain is not None and plain.kind == "usage_limit" and plain.resets_at is None
    soon = classify_failure("m", '{"error":{"type":"usage_limit_reached","resets_in_seconds":60}}', now=1000.0)
    assert soon is not None and soon.resets_at == 1060
    assert classify_failure("m", "connection reset") is None
