"""Claude Code step executor against a fake ``claude`` that replays recorded stream-json fixtures."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import stat
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.services.workflow_runs import executor_claude_code as module
from app.services.workflow_runs.executor_claude_code import ClaudeCodeExecutor, transcript_path
from app.services.workflow_runs.executors import get_executor
from app.services.workflow_runs.packet import GitState, build_packet, parse_handoff

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "claude_code_cli"
MODEL = "claude-opus-5-5"
HANDOFF = '```handoff\n{"summary": "wrote hello.txt", "decisions": ["plain text"], "files": ["hello.txt"], "open_questions": []}\n```'


def fixture(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (FIXTURES / f"{name}.jsonl").read_text().splitlines() if line.strip()]


def success_stream(text: str, *, session_id: str = "sess-1") -> list[dict[str, Any]]:
    events = copy.deepcopy(fixture("success_continuation_turn"))
    for event in events:
        event["session_id"] = session_id
        if event["type"] == "assistant":
            event["message"]["model"] = MODEL
            event["message"]["content"] = [{"type": "text", "text": text}]
        if event["type"] == "result":
            event["result"] = text
            event["modelUsage"] = {MODEL: {"inputTokens": 2}}
    return events


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = tmp_path / "wt"
    path.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "base"]):
        subprocess.run(["git", *args], cwd=path, check=True, env=env)
    return path


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def install(events: list[dict[str, Any]]) -> Path:
        stream = tmp_path / "stream.jsonl"
        stream.write_text("".join(json.dumps(e) + "\n" for e in events))
        script = tmp_path / "claude"
        script.write_text(
            f'#!/bin/sh\nprintf \'%s\\n\' "$@" > {tmp_path}/args.txt\ncat > {tmp_path}/stdin.txt\ncat {stream}\n'
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setattr(module, "claude_binary", lambda: str(script))
        monkeypatch.setattr(module, "claude_home", lambda: tmp_path / "claude-home")
        return tmp_path

    return install


def packet(test_hooks: dict[str, Any] | None = None, thinking_level: str | None = None, level: str | None = None, **kwargs: Any):
    return replace(build_packet(
        run_goal="goal",
        step_key="implement",
        instructions="create hello.txt",
        acceptance=[],
        git=GitState(),
        prior_steps=[],
        run_dir="/run",
        context_window=100_000,
        budget_fraction=0.25,
        **kwargs,
    ), test_hooks=test_hooks, thinking_level=thinking_level, level=level)


async def run(worktree: Path, tmp_path: Path, **kwargs: Any):
    beats: list[Any] = []

    async def on_event(event: Any) -> None:
        beats.append(event)

    result = await ClaudeCodeExecutor().run(packet(**kwargs), MODEL, worktree, tmp_path / "run", on_event)
    return result, beats


async def test_agent_thinking_level_becomes_the_effort(fake_claude, worktree, tmp_path) -> None:
    fake_claude(success_stream(HANDOFF))
    await run(worktree, tmp_path, thinking_level="low")
    args = (tmp_path / "args.txt").read_text().splitlines()
    assert args[args.index("--effort") + 1] == "low"


async def test_steps_run_lean_by_default_and_full_on_request(fake_claude, worktree, tmp_path) -> None:
    fake_claude(success_stream(HANDOFF))
    await run(worktree, tmp_path)
    args = (tmp_path / "args.txt").read_text().splitlines()
    assert args[args.index("--tools") + 1] == "Read,Edit,Write,Bash"
    assert {"--disable-slash-commands", "--strict-mcp-config", "--exclude-dynamic-system-prompt-sections"} <= set(args)
    await run(worktree, tmp_path, level="full")
    args = (tmp_path / "args.txt").read_text().splitlines()
    assert "--tools" not in args and "--strict-mcp-config" not in args


def test_step_level_must_be_a_configured_level() -> None:
    from pydantic import ValidationError

    from app.services.workflow_runs.schemas import StepDefinition

    assert StepDefinition(key="a", instructions="x", agent_slug="coder", level="full").level == "full"
    with pytest.raises(ValidationError):
        StepDefinition(key="a", instructions="x", agent_slug="coder", level="huge")


def test_registered_under_its_kind() -> None:
    assert isinstance(get_executor("claude_code"), ClaudeCodeExecutor)


def test_packet_asks_for_a_handoff_block_and_parses_it() -> None:
    assert "```handoff" in packet().render()
    note = parse_handoff(f"done\n{HANDOFF}")
    assert note and note["summary"] == "wrote hello.txt" and note["files"] == ["hello.txt"]
    assert parse_handoff("```handoff\nnot json\n```") is None
    assert parse_handoff("no block") is None


async def test_success_returns_handoff_usage_session_and_transcript(fake_claude, worktree, tmp_path) -> None:
    fake_claude(success_stream(f"All done.\n{HANDOFF}"))
    native = tmp_path / "claude-home" / "projects" / "-some-dir" / "sess-1.jsonl"
    native.parent.mkdir(parents=True)
    native.write_text("{}\n")
    result, beats = await run(worktree, tmp_path, context="canonical context")
    assert result.status == "completed" and result.outcome is None
    assert result.handoff and result.handoff["summary"] == "wrote hello.txt"
    assert result.served_models == [MODEL]
    assert result.native_session_id == "sess-1" and result.transcript_path == str(native)
    assert result.usage["input_tokens"] == 2 and result.usage["cache_read_tokens"] == 6052
    assert result.usage["output_tokens"] == 38 and result.usage["by_model"] == {MODEL: {"inputTokens": 2}}
    assert beats and beats[0]["type"] == "claude_code_event"
    args = (tmp_path / "args.txt").read_text().splitlines()
    assert args[:2] == ["-p", "--input-format"] and "--no-session-persistence" not in args
    assert args[args.index("--model") + 1] == MODEL
    assert args[args.index("--effort") + 1] == "high"  # the executor default; the packet carries no agent level here
    assert args[args.index("--settings") + 1] == '{"switchModelsOnFlag": false}'
    assert args[args.index("--append-system-prompt") + 1] == "canonical context"
    sent = json.loads((tmp_path / "stdin.txt").read_text())
    assert sent["message"]["content"][0]["text"].startswith("# Run goal")


async def test_usage_carries_the_subscription_window_use_the_cli_reported(fake_claude, worktree, tmp_path) -> None:
    stream = success_stream(f"Done.\n{HANDOFF}")
    windows = {"five_hour": {"utilization": 0.07, "status": "allowed"}, "seven_day": {"utilization": 0.5}}
    stream.insert(1, {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": windows}})
    fake_claude(stream)
    result, _ = await run(worktree, tmp_path)
    assert result.usage["rate_limit_windows"] == {"five_hour": 0.07, "seven_day": 0.5}
    assert "rate_limit_resets" not in result.usage  # the CLI named no reset times
    assert result.usage["rate_limit_observed_at"] > 0


async def test_window_resets_come_from_the_window_or_the_event_that_names_it(fake_claude, worktree, tmp_path) -> None:
    stream = success_stream(f"Done.\n{HANDOFF}")
    windows = {"five_hour": {"utilization": 0.07, "resetsAt": 1793035965}, "seven_day": {"utilization": 0.5}}
    info = {"status": "allowed", "unifiedWindows": windows, "rateLimitType": "seven_day", "resetsAt": 1793600626}
    stream.insert(1, {"type": "rate_limit_event", "rate_limit_info": info})
    fake_claude(stream)
    result, _ = await run(worktree, tmp_path)
    assert result.usage["rate_limit_resets"] == {"five_hour": 1793035965, "seven_day": 1793600626}


async def test_claude_cost_is_the_clis_list_price_labelled_as_a_subscription_equivalent(
    fake_claude, worktree, tmp_path, monkeypatch
) -> None:
    from types import SimpleNamespace

    stream = success_stream(f"Done.\n{HANDOFF}")
    next(e for e in stream if e["type"] == "result")["total_cost_usd"] = 0.0417
    fake_claude(stream)
    monkeypatch.setattr("app.constants.catalog.get_model_entry", lambda _m: SimpleNamespace(provider="claude", capabilities=None))
    result, _ = await run(worktree, tmp_path)
    usage = result.usage
    assert usage["total_cost_usd"] == 0.0417  # the key earlier readers know stays
    assert (usage["cost_usd"], usage["cost_basis"], usage["cost_source"]) == (0.0417, "subscription_equiv", "provider_reported")


async def test_missing_handoff_block_falls_back_to_a_marked_note(fake_claude, worktree, tmp_path) -> None:
    (worktree / "hello.txt").write_text("hi\n")
    fake_claude(success_stream("I made hello.txt."))
    result, _ = await run(worktree, tmp_path)
    assert result.status == "completed" and result.handoff
    assert result.handoff["summary"] == "I made hello.txt."
    assert result.handoff["files"] == ["hello.txt"]
    assert any("fallback handoff" in item for item in result.handoff["decisions"])


async def test_refusal_fails_with_category_and_keeps_only_earlier_progress(fake_claude, worktree, tmp_path) -> None:
    earlier = success_stream("step one")[1]
    refused = fixture("refusal_assistant")
    fake_claude([earlier, *refused, {"type": "result", "subtype": "success", "is_error": True, "result": "refused"}])
    result, _ = await run(worktree, tmp_path)
    assert result.status == "failed" and result.handoff is None
    assert (result.outcome.kind, result.outcome.category) == ("refused", "cyber")
    assert result.outcome.requested_model == MODEL
    assert list(result.progress) == ["step one"]


async def test_model_switch_is_a_substituted_outcome(fake_claude, worktree, tmp_path) -> None:
    switched = [*fixture("model_refusal_fallback"),
        {"type": "result", "subtype": "success", "is_error": False, "result": HANDOFF, "modelUsage": {"claude-opus-4-8": {}}}
    ]
    fake_claude(switched)
    result, _ = await run(worktree, tmp_path)
    assert result.outcome and result.outcome.kind == "substituted"
    assert result.outcome.served_model == "claude-opus-4-8" and result.outcome.category
    assert result.status == "completed" and result.handoff
    assert "claude-opus-4-8" in result.served_models


async def test_usage_limit_carries_window_and_reset(fake_claude, worktree, tmp_path) -> None:
    fake_claude(fixture("usage_limit"))
    result, _ = await run(worktree, tmp_path)
    assert result.status == "failed"
    assert (result.outcome.kind, result.outcome.window, result.outcome.resets_at) == (
        "usage_limit",
        "five_hour",
        1793155200,
    )


async def test_crash_without_result_is_an_error(fake_claude, worktree, tmp_path) -> None:
    fake_claude([])
    result, _ = await run(worktree, tmp_path)
    assert result.status == "failed" and result.outcome is None and result.error


async def test_injected_refusal_looks_like_a_real_one(fake_claude, worktree, tmp_path) -> None:
    turns = []
    for index, text in enumerate(("one", "two", "three")):
        event = copy.deepcopy(success_stream(text)[1])
        event["message"]["id"] = f"msg_{index}"
        turns.append(event)
    fake_claude(turns)
    hooks = {"refuse_after_turn": 2, "refusal_category": "bio"}
    result, _ = await run(worktree, tmp_path, test_hooks=hooks)
    assert result.status == "failed" and result.handoff is None
    assert (result.outcome.kind, result.outcome.category) == ("refused", "bio")
    assert list(result.progress) == ["one", "two"]
    # Without the hook (the engine drops it while hooks are disabled) the same stream is not refused.
    plain, _ = await run(worktree, tmp_path)
    assert plain.outcome is None


def stream_event(inner: dict[str, Any]) -> dict[str, Any]:
    return {"type": "stream_event", "event": inner, "session_id": "sess-1", "uuid": "u", "parent_tool_use_id": None}


def partial_lines() -> list[dict[str, Any]]:
    """What ``--include-partial-messages`` adds around a turn: thinking and text deltas, a tool call, a provider retry."""

    start = lambda block: stream_event({"type": "content_block_start", "index": 0, "content_block": block})  # noqa: E731
    delta = lambda part: stream_event({"type": "content_block_delta", "index": 0, "delta": part})  # noqa: E731
    return [
        {"type": "system", "subtype": "api_retry", "attempt": 1, "max_retries": 10, "retry_delay_ms": 500,
         "error_status": 529, "error": "overloaded", "session_id": "sess-1"},
        stream_event({"type": "message_start", "message": {"id": "m", "role": "assistant", "content": []}}),
        start({"type": "thinking", "thinking": ""}),
        delta({"type": "thinking_delta", "thinking": "let me think"}),
        delta({"type": "signature_delta", "signature": "sig"}),
        start({"type": "text", "text": ""}),
        delta({"type": "text_delta", "text": "I will write it"}),
        start({"type": "tool_use", "id": "tu", "name": "Write", "input": {}}),
        delta({"type": "input_json_delta", "partial_json": '{"file'}),
        stream_event({"type": "message_stop"}),
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu"}]},
         "session_id": "sess-1"},
        start({"type": "thinking", "thinking": ""}),
    ]


async def test_partial_messages_are_liveness_only_and_the_transcript_and_usage_are_unchanged(
    fake_claude, worktree, tmp_path
) -> None:
    from .support import recording_live

    plain = success_stream(f"All done.\n{HANDOFF}")
    fake_claude(plain)
    before, _ = await run(worktree, tmp_path)
    assert "--include-partial-messages" in (tmp_path / "args.txt").read_text().splitlines()

    with_partials = [plain[0], *partial_lines(), *plain[1:]]
    fake_claude(with_partials)
    with recording_live() as live:
        after, _ = await run(worktree, tmp_path)
    for field in ("status", "handoff", "usage", "served_models", "native_session_id", "progress", "outcome", "error"):
        assert getattr(after, field) == getattr(before, field), field
    assert live.history == ["waiting", "provider_retry", "thinking", "writing", "tool:Write", "waiting", "thinking"]
    assert live.last_event_at is not None


def test_stream_events_are_ignored_by_the_turn_observer_and_the_attempt() -> None:
    from app.llm.provider_support.claude_stream import ClaudeTurnObserver

    observer, state = ClaudeTurnObserver(), module._Attempt(MODEL, MODEL, {"progress_items": 4, "progress_output_chars": 100}, None)
    for event in partial_lines():
        observer.handle(event)
        state.handle(event)
    assert observer.result is None and observer.refusal is None and not observer.answer_text and not observer.succeeded()
    assert not state.turns and not state.served and state.progress.items == []


async def test_the_loop_clock_jump_really_fires_wait_for_deadlines() -> None:
    """Guards the long-run tests below: a two-hour jump does expire a 3600 s ``wait_for``."""

    from .support import loop_clock

    with loop_clock() as clock:
        waiting = asyncio.create_task(asyncio.wait_for(asyncio.sleep(5), 3600))
        await asyncio.sleep(0)
        clock.jump(2 * 3600)
        with pytest.raises(TimeoutError):
            await waiting


async def test_a_run_past_the_old_hour_limit_is_not_ended(fake_claude, worktree, tmp_path) -> None:
    from .support import loop_clock

    fake_claude(success_stream(f"All done.\n{HANDOFF}"))
    with loop_clock() as clock:
        async def on_event(_event: Any) -> None:
            if not clock.offset:
                clock.jump(2 * 3600)
                await asyncio.sleep(0.05)

        result = await ClaudeCodeExecutor().run(packet(), MODEL, worktree, tmp_path / "run", on_event)
    assert result.status == "completed" and result.error is None


def test_transcript_path_finds_the_native_jsonl(tmp_path: Path) -> None:
    worktree = tmp_path / "w.t"
    worktree.mkdir()
    home = tmp_path / "home"
    expected = home / "projects" / str(worktree.resolve()).replace("/", "-").replace(".", "-") / "abc.jsonl"
    expected.parent.mkdir(parents=True)
    expected.write_text("{}")
    assert transcript_path("abc", worktree, home) == expected
    assert transcript_path("missing", worktree, home) is None


def test_claude_effort_follows_the_packet_thinking_level() -> None:
    for level in ("low", "medium", "high"):
        argv, _ = ClaudeCodeExecutor().command(packet(thinking_level=level), MODEL, "claude")
        assert argv[argv.index("--effort") + 1] == level
