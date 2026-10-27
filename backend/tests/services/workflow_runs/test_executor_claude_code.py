"""Claude Code step executor against a fake ``claude`` that replays recorded stream-json fixtures."""

from __future__ import annotations

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


def packet(test_hooks: dict[str, Any] | None = None, thinking_level: str | None = None, **kwargs: Any):
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
    ), test_hooks=test_hooks, thinking_level=thinking_level)


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


def test_transcript_path_finds_the_native_jsonl(tmp_path: Path) -> None:
    worktree = tmp_path / "w.t"
    worktree.mkdir()
    home = tmp_path / "home"
    expected = home / "projects" / str(worktree.resolve()).replace("/", "-").replace(".", "-") / "abc.jsonl"
    expected.parent.mkdir(parents=True)
    expected.write_text("{}")
    assert transcript_path("abc", worktree, home) == expected
    assert transcript_path("missing", worktree, home) is None
