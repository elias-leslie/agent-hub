"""Agent Hub step executor: the completion path is faked, the mapping to StepResult is the unit."""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from app.api.complete.types import CompletionInternalResult
from app.llm.types import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
)
from app.llm.utils.outcomes import ProviderOutcome, record_outcome
from app.services.workflow_runs import agent_hub_transcript
from app.services.workflow_runs.agent_hub_transcript import Transcript, record_transcript
from app.services.workflow_runs.executor_agent_hub import AgentHubExecutor
from app.services.workflow_runs.executors import get_executor
from app.services.workflow_runs.packet import AttemptRef, GitState, build_packet

MODEL = "claude-opus-5-5"
HANDOFF = '```handoff\n{"summary": "wrote hello.txt", "decisions": [], "files": ["hello.txt"], "open_questions": []}\n```'


@dataclass
class Agent:
    temperature: float = 0.3
    thinking_level: str | None = "high"


def assistant(
    content: list[Any], stop: str = "stop", *, model: str = MODEL, provider: str = "claude", **kwargs: Any
) -> AssistantMessage:
    usage = Usage(input=10, output=5, cache_read=100, cache_write=20, total_tokens=135)
    usage.cost.total = 0.01
    return AssistantMessage(
        content=content, api="claude-code-cli", provider=provider, model=model, usage=usage,
        stop_reason=stop, timestamp=0, response_model=model, **kwargs,
    )


def internal(messages: list[AssistantMessage]) -> CompletionInternalResult:
    return CompletionInternalResult(
        message=messages[-1], usage_messages=messages, session_id="attempt-1", memory_uuids=[], cited_uuids=[]
    )


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = tmp_path / "wt"
    path.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for args in (
        ["init", "-q", "-b", "main"],
        # A global core.hooksPath would otherwise run the user's hooks on the tests' commits.
        ["config", "core.hooksPath", str(path / ".git/hooks")],
        ["commit", "-q", "--allow-empty", "-m", "base"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True, env=env)
    return path


def packet(
    test_hooks: dict[str, Any] | None = None,
    level: str | None = None,
    thinking_level: str | None = None,
    acceptance: list[str] | None = None,
):
    base = build_packet(
        run_goal="goal", step_key="implement", instructions="create hello.txt", acceptance=acceptance or [],
        git=GitState(), prior_steps=[], run_dir="/run", context_window=100_000, budget_fraction=0.25,
    )
    return replace(base, test_hooks=test_hooks, level=level, thinking_level=thinking_level, attempt=AttemptRef("attempt-1", "run-1", "proj", "coder"))


PROVISIONED = [{"name": "bash"}, {"name": "write_file"}]


class Calls(list):
    """The completion calls made, plus the transcripts the executor handed to its writer."""

    transcripts: list[Any]


@dataclass
class Event:
    type: str
    message: Any = None
    tool_call: Any = None
    result: Any = None
    reason: str = ""


def tool_text(result: ToolResultMessage) -> str:
    return "".join(b.text for b in result.content if isinstance(b, TextContent))


def tool_result(call: ToolCall, text: str, *, error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=call.id, tool_name=call.name, content=[TextContent(text=text)], is_error=error, timestamp=0
    )


async def run(
    worktree: Path, tmp_path: Path, messages: list[AssistantMessage], provisioned=None, loop_events=(), writer=None,
    model: str = MODEL, **kwargs: Any,
):
    calls = Calls()
    transcripts = calls.transcripts = []

    async def complete(**kw: Any) -> CompletionInternalResult:
        calls.append(kw)
        for event in loop_events:  # what the tool loop would report, replayed in order
            kw["on_loop_event"](event)
        return internal(messages)

    async def write(transcript: Transcript) -> None:
        transcripts.append(transcript)

    async def agent(_slug: str) -> Agent:
        return Agent()

    async def tools(_slug: str, _project: str) -> list[dict[str, Any]]:
        return PROVISIONED if provisioned is None else provisioned

    executor = AgentHubExecutor(
        complete=complete, agent_loader=agent, tool_provisioner=tools, transcript_writer=writer or write
    )

    async def on_event(_event: Any) -> None:
        return None

    result = await executor.run(packet(**kwargs), model, worktree, tmp_path, on_event)
    return result, calls


async def test_packet_effort_wins_over_the_agents_thinking_level(worktree, tmp_path) -> None:
    turns = [assistant([TextContent(text=HANDOFF)])]
    _, calls = await run(worktree, tmp_path, turns, thinking_level="low")
    assert calls[0]["thinking_level"] == "low"  # the test agent's own level is "high"
    _, calls = await run(worktree, tmp_path, turns)
    assert calls[0]["thinking_level"] == "high"


def test_registered_under_its_kind() -> None:
    assert isinstance(get_executor("agent_hub"), AgentHubExecutor)


async def test_runs_the_tool_loop_on_the_worktree_with_the_attempt_session(worktree, tmp_path) -> None:
    call = ToolCall(id="t1", name="write_file", arguments={"path": "hello.txt"})
    turns = [assistant([call], "toolUse"), assistant([TextContent(text=f"Done.\n{HANDOFF}")])]
    result, calls = await run(worktree, tmp_path, turns)
    kw = calls[0]
    assert kw["tools"] == PROVISIONED
    assert kw["execute_tools"] is True and kw["working_dir"] == str(worktree)
    assert kw["session_id"] == "attempt-1" and kw["parent_session_id"] == "run-1"
    assert kw["agent_slug"] == "coder" and kw["project_id"] == "proj" and kw["temperature"] == 0.3
    assert kw["db"] is None and kw["messages"][-1]["content"].startswith("# Run goal")
    assert result.status == "completed" and result.outcome is None
    assert result.handoff and result.handoff["files"] == ["hello.txt"]
    assert result.served_models == [MODEL] and result.native_session_id == "attempt-1"
    assert result.usage["input_tokens"] == 20 and result.usage["cache_read_tokens"] == 200
    assert result.usage["cost_usd"] == pytest.approx(0.02)


async def test_refused_turn_fails_with_outcome_and_is_not_progress(worktree, tmp_path) -> None:
    call = ToolCall(id="t1", name="write_file", arguments={"path": "a.py"})
    refused = assistant([TextContent(text="can't help")], "error", error_message="refused")
    record_outcome(refused, ProviderOutcome("refused", MODEL, category="cyber"))
    result, _ = await run(worktree, tmp_path, [assistant([TextContent(text="working")], "toolUse"), assistant([call], "toolUse"), refused])
    assert result.status == "failed" and result.handoff is None
    assert (result.outcome.kind, result.outcome.category) == ("refused", "cyber")
    assert result.progress[0] == "working" and "can't help" not in " ".join(result.progress)


async def test_usage_limit_and_plain_error(worktree, tmp_path) -> None:
    limited = assistant([], "error", error_message="429")
    record_outcome(limited, ProviderOutcome("usage_limit", MODEL, window="five_hour", resets_at=5))
    result, _ = await run(worktree, tmp_path, [limited])
    assert result.status == "failed" and result.outcome.kind == "usage_limit" and result.outcome.resets_at == 5
    failed, _ = await run(worktree, tmp_path, [assistant([], "error", error_message="boom")])
    assert failed.status == "failed" and failed.outcome is None and failed.error == "boom"


async def test_substituted_but_finished_completes_with_the_outcome(worktree, tmp_path) -> None:
    done = assistant([TextContent(text=HANDOFF)], model="claude-opus-4-8")
    record_outcome(done, ProviderOutcome("substituted", MODEL, served_model="claude-opus-4-8", category="cyber"))
    result, _ = await run(worktree, tmp_path, [done])
    assert result.status == "completed" and result.outcome.kind == "substituted"
    assert result.served_models == ["claude-opus-4-8"]


async def test_missing_handoff_block_uses_the_marked_fallback(worktree, tmp_path) -> None:
    (worktree / "hello.txt").write_text("hi\n")
    result, _ = await run(worktree, tmp_path, [assistant([TextContent(text="made it")])])
    assert result.handoff["summary"] == "made it" and result.handoff["files"] == ["hello.txt"]
    assert any("fallback handoff" in d for d in result.handoff["decisions"])


async def test_injected_refusal_caps_the_loop_and_drops_the_closeout_turn(worktree, tmp_path) -> None:
    call = ToolCall(id="t1", name="bash", arguments={"command": "ls"})
    turns = [assistant([call], "toolUse"), assistant([call], "toolUse"), assistant([TextContent(text="closeout")])]
    hooks = {"refuse_after_turn": 2, "refusal_category": "bio"}
    result, calls = await run(worktree, tmp_path, turns, test_hooks=hooks)
    assert calls[0]["max_turns"] == 2
    assert result.status == "failed" and (result.outcome.kind, result.outcome.category) == ("refused", "bio")
    assert len(result.progress) == 2
    # A loop that finishes within the allowed turns was never refused.
    finished, _ = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], test_hooks=hooks)
    assert finished.status == "completed"


async def test_an_attempt_runs_with_no_turn_budget(worktree, tmp_path) -> None:
    _, calls = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])])
    assert calls[0]["max_turns"] is None


async def test_a_turn_budget_that_is_reached_fails_the_step_explicitly(worktree, tmp_path) -> None:
    (worktree / "hello.txt").write_text("hi\n")
    exhausted = Event(type="turn_budget_exhausted")
    exhausted.max_turns = 7  # type: ignore[attr-defined]
    result, _ = await run(
        worktree, tmp_path, [assistant([TextContent(text=f"closeout\n{HANDOFF}")])], loop_events=[exhausted]
    )
    assert result.status == "failed" and result.handoff is None
    assert result.error and result.error.startswith("turn_budget_exhausted:") and "7 turns" in result.error


async def test_packet_without_an_attempt_cannot_run(worktree, tmp_path) -> None:
    async def on_event(_event: Any) -> None:
        return None

    result = await AgentHubExecutor().run(replace(packet(), attempt=None), MODEL, worktree, tmp_path, on_event)
    assert result.status == "failed" and "attempt" in (result.error or "")


PROVISIONED_ALL = [{"name": n} for n in ("bash", "read_file", "edit_file", "write_file", "search_scratch_context", "manage_tasks", "consult_agent")]


async def test_lean_is_the_default_level_with_core_tools_and_a_cwd_prompt(worktree, tmp_path) -> None:
    _, calls = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], provisioned=PROVISIONED_ALL)
    kw = calls[0]
    assert [t["name"] for t in kw["tools"]] == ["bash", "read_file", "edit_file", "write_file", "search_scratch_context"]
    system, user = kw["messages"]
    assert system["role"] == "system" and user["role"] == "user" and user["content"].startswith("# Run goal")
    assert f"<cwd>\n{worktree}\n</cwd>" in system["content"]
    assert "- bash: " in system["content"] and "manage_tasks" not in system["content"] and "{" not in system["content"]


async def test_full_level_keeps_the_agents_whole_tool_set_and_adds_no_prompt(worktree, tmp_path) -> None:
    _, calls = await run(
        worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], provisioned=PROVISIONED_ALL, level="full"
    )
    assert calls[0]["tools"] == PROVISIONED_ALL
    assert [m["role"] for m in calls[0]["messages"]] == ["user"]


async def test_lean_never_adds_a_tool_and_never_leaves_the_step_without_any(worktree, tmp_path) -> None:
    only = [{"name": "bash"}, {"name": "write_file"}, {"name": "manage_tasks"}]
    _, calls = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], provisioned=only)
    assert [t["name"] for t in calls[0]["tools"]] == ["bash", "write_file"]
    assert "- read_file" not in calls[0]["messages"][0]["content"]
    other = [{"name": "manage_tasks"}]
    _, calls = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], provisioned=other, level="full")
    assert calls[0]["tools"] == other and [m["role"] for m in calls[0]["messages"]] == ["user"]


READ_TIER = [{"name": "read_file"}]


async def test_a_tool_set_without_shell_and_write_ends_the_attempt_before_any_model_call_with_a_typed_error(
    worktree, tmp_path
) -> None:
    result, calls = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], provisioned=READ_TIER)
    assert calls == [] and result.status == "failed" and result.tools == ["read_file"]
    assert result.error.startswith("tools_unavailable: tool level 'lean' allows only [read_file]")
    assert "bash" in result.error and "edit_file or write_file" in result.error
    assert result.outcome is None and result.served_models == ()


async def test_acceptance_commands_need_a_shell_and_a_write_tool_even_at_the_full_level(worktree, tmp_path) -> None:
    turns = [assistant([TextContent(text=HANDOFF)])]
    refused, calls = await run(
        worktree, tmp_path, turns, provisioned=READ_TIER, level="full", acceptance=["test -f hello.txt"]
    )
    assert calls == [] and refused.error.startswith("tools_unavailable:")
    no_write, calls = await run(
        worktree, tmp_path, turns, provisioned=[{"name": "bash"}, {"name": "read_file"}], level="full", acceptance=["true"]
    )
    assert calls == [] and "edit_file or write_file" in no_write.error and "needs bash and" not in no_write.error
    # Without acceptance commands the full level asks for nothing in particular, so a narrow set still runs.
    allowed, calls = await run(worktree, tmp_path, turns, provisioned=READ_TIER, level="full")
    assert len(calls) == 1 and allowed.status == "completed" and allowed.tools == ["read_file"]


async def test_the_tools_the_attempt_got_are_recorded_on_a_finished_attempt(worktree, tmp_path) -> None:
    result, _ = await run(
        worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], provisioned=PROVISIONED_ALL
    )
    assert result.tools == ["bash", "read_file", "edit_file", "write_file", "search_scratch_context"]


async def test_read_level_gives_only_read_tools_and_permits_exactly_those_calls(worktree, tmp_path) -> None:
    result, calls = await run(
        worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], provisioned=PROVISIONED_ALL, level="read"
    )
    assert result.status == "completed" and result.tools == ["read_file"]
    assert [t["name"] for t in calls[0]["tools"]] == ["read_file"]
    assert calls[0]["permitted_tools"] == frozenset({"read_file"})
    assert "edit_file" not in calls[0]["messages"][0]["content"] and "- read_file" in calls[0]["messages"][0]["content"]


async def test_read_level_never_falls_back_to_the_agents_own_tools_and_refuses_acceptance_commands(
    worktree, tmp_path
) -> None:
    turns = [assistant([TextContent(text=HANDOFF)])]
    result, calls = await run(worktree, tmp_path, turns, provisioned=PROVISIONED_ALL, level="read", acceptance=["true"])
    assert calls == [] and result.error.startswith("tools_unavailable: tool level 'read' allows only [read_file]")
    other, calls = await run(worktree, tmp_path, turns, provisioned=[{"name": "bash"}, {"name": "write_file"}], level="read")
    assert other.status == "completed" and other.tools == [] and calls[0]["tools"] == []
    assert calls[0]["permitted_tools"] == frozenset()


async def test_every_attempt_permits_exactly_the_tools_it_got(worktree, tmp_path) -> None:
    _, calls = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], provisioned=PROVISIONED_ALL)
    assert calls[0]["permitted_tools"] == frozenset(t["name"] for t in calls[0]["tools"])


async def test_the_project_chat_tier_does_not_narrow_a_workflow_attempts_tools() -> None:
    from app.services.workflow_runs.executor_agent_hub import provision_tools

    # No tier lookup is involved: the agent's own tools come back, bash and the write tools included.
    names = {tool["name"] for tool in await provision_tools("coder", "any-project") or []}
    assert {"bash", "read_file", "edit_file", "write_file"} <= names


async def test_unknown_level_fails_before_any_model_call(worktree, tmp_path) -> None:
    result, calls = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], level="huge")
    assert result.status == "failed" and "unknown level" in result.error and calls == []


async def test_transcript_carries_the_turns_tool_results_retries_and_input(worktree, tmp_path) -> None:
    call = ToolCall(id="t1", name="write_file", arguments={"path": "hello.txt"})
    turns = [assistant([call], "toolUse"), assistant([TextContent(text=f"Done.\n{HANDOFF}")])]
    events = [
        Event("done", message=turns[0]),
        Event("tool_run_complete", tool_call=call, result=tool_result(call, "wrote 3 bytes")),
        Event("turn_retry", reason="stream stalled"),
        Event("done", message=turns[1]),
    ]
    result, calls = await run(worktree, tmp_path, turns, loop_events=events)
    (transcript,) = calls.transcripts
    assert result.status == "completed" and result.native_session_id == "attempt-1"
    assert (transcript.session_id, transcript.agent_slug, transcript.requested_model) == ("attempt-1", "coder", MODEL)
    assert [m["role"] for m in transcript.input_messages] == ["system", "user"]
    assert list(transcript.turns) == turns and transcript.error is None
    assert tool_text(transcript.tool_results["t1"]) == "wrote 3 bytes"
    assert list(transcript.retries) == [(1, "stream stalled")]


async def test_reasoning_tokens_the_provider_reports_reach_the_attempt_usage(worktree, tmp_path) -> None:
    first, second = assistant([TextContent(text="a")], "toolUse"), assistant([TextContent(text=HANDOFF)])
    first.usage.reasoning, second.usage.reasoning = 7, 5
    result, _ = await run(worktree, tmp_path, [first, second])
    assert result.usage["reasoning_tokens"] == 12 and result.usage["output_tokens"] == 10


async def test_served_model_per_turn_is_the_catalog_identity_unless_the_provider_switched(worktree, tmp_path) -> None:
    same = assistant([TextContent(text="a")], "toolUse")
    same.response_model = "claude-opus-5-5"
    switched = assistant([TextContent(text=HANDOFF)], model=MODEL)
    switched.response_model = "claude-opus-4-8"
    record_outcome(switched, ProviderOutcome("substituted", MODEL, served_model="claude-opus-4-8"))
    result, calls = await run(worktree, tmp_path, [same, switched])
    assert result.served_models == [MODEL, "claude-opus-4-8"] and result.outcome.kind == "substituted"
    assert calls.transcripts[0].requested_model == MODEL


async def test_interrupted_outcome_reaches_the_attempt_result(worktree, tmp_path) -> None:
    stalled = assistant([], "error", error_message="stream stalled")
    record_outcome(stalled, ProviderOutcome("interrupted", MODEL))
    result, _ = await run(worktree, tmp_path, [stalled])
    assert result.status == "failed" and result.outcome.kind == "interrupted"


async def test_failures_before_a_completion_still_leave_the_input_and_the_error(worktree, tmp_path) -> None:
    async def boom(**_kw: Any) -> Any:
        raise RuntimeError("no credentials")

    transcripts: list[Transcript] = []

    async def write(transcript: Transcript) -> None:
        transcripts.append(transcript)

    async def agent(_slug: str) -> Agent:
        return Agent()

    async def tools(_slug: str, _project: str) -> list[dict[str, Any]]:
        return PROVISIONED

    async def on_event(_event: Any) -> None:
        return None

    executor = AgentHubExecutor(complete=boom, agent_loader=agent, tool_provisioner=tools, transcript_writer=write)
    result = await executor.run(packet(), MODEL, worktree, tmp_path, on_event)
    assert result.status == "failed" and "no credentials" in (result.error or "")
    assert list(transcripts[0].turns) == [] and "no credentials" in (transcripts[0].error or "")
    assert transcripts[0].input_messages[-1]["role"] == "user"


async def test_a_transcript_that_cannot_be_written_does_not_fail_the_step(worktree, tmp_path) -> None:
    async def broken(_transcript: Transcript) -> None:
        raise RuntimeError("db down")

    result, _ = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], writer=broken)
    assert result.status == "completed"


class FakeDb:
    """Stands in for the session: the event and cost writers are patched, so only the ordering is exercised."""

    async def execute(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []  # no events stored yet: the lookup of already-saved source identities finds nothing


async def test_record_transcript_writes_ordered_events_with_usage_once_per_turn(monkeypatch) -> None:
    events: list[dict[str, Any]] = []
    costs: list[tuple[Any, ...]] = []

    async def store_event(_db, session_id, event_type, **kw):
        events.append({"session_id": session_id, "type": event_type, **kw})

    async def log_usage(_db, session_id, model, input_tokens, output_tokens, cost, **kw):
        costs.append((session_id, model, input_tokens, output_tokens, kw["cache_read_tokens"]))

    async def lock(_db, _session_id):
        return None

    monkeypatch.setattr(agent_hub_transcript, "store_event", store_event)
    monkeypatch.setattr(agent_hub_transcript, "log_token_usage", log_usage)
    monkeypatch.setattr(agent_hub_transcript, "lock_session_event_ingestion", lock)
    call = ToolCall(id="t1", name="bash", arguments={"command": "ls"})
    first = assistant([ThinkingContent(thinking="plan it"), call], "toolUse")
    first.usage.reasoning = 3
    refused = assistant([], "error", error_message="refused")
    record_outcome(refused, ProviderOutcome("refused", MODEL, category="cyber"))
    transcript = Transcript(
        "attempt-1", "coder", MODEL,
        input_messages=[{"role": "system", "content": "rules"}, {"role": "user", "content": "goal"}],
        turns=[first, refused], tool_results={"t1": tool_result(call, "a.txt\n")}, retries=[(1, "stalled")],
        error="timeout",
    )
    await record_transcript(FakeDb(), transcript)
    kinds = [e["type"] for e in events]
    assert kinds == [
        "system_message", "user_message", "thinking", "tool_use", "tool_result", "error", "error", "error",
    ]
    thinking, tool_use, tool_res = events[2], events[3], events[4]
    assert thinking["usage"]["reasoning_tokens"] == 3 and thinking["usage"]["served_model"] == MODEL
    assert thinking["tokens"] == 3 and tool_use["usage"] is None  # usage rides on the first event of the turn
    assert tool_use["call_id"] == tool_res["call_id"] == "t1" and tool_res["tool_output"]["is_error"] is False
    assert events[5]["content"].startswith("turn_retry: stalled")
    assert events[6]["usage"]["provider_outcome"]["kind"] == "refused" and events[7]["content"] == "timeout"
    assert [c[:4] for c in costs] == [("attempt-1", MODEL, 10, 5)] * 2


async def test_a_crash_after_a_tool_turn_keeps_the_turn_and_its_result_then_the_error(worktree, tmp_path) -> None:
    call = ToolCall(id="t1", name="write_file", arguments={"path": "hello.txt"})
    turn = assistant([call], "toolUse")
    transcripts: list[Transcript] = []

    async def write(transcript: Transcript) -> None:
        transcripts.append(transcript)

    async def crash(**kw: Any) -> Any:
        kw["on_loop_event"](Event("done", message=turn))
        kw["on_loop_event"](Event("tool_run_complete", tool_call=call, result=tool_result(call, "wrote 3 bytes")))
        raise ConnectionResetError("provider closed the connection")

    async def agent(_slug: str) -> Agent:
        return Agent()

    async def tools(_slug: str, _project: str) -> list[dict[str, Any]]:
        return PROVISIONED

    async def on_event(_event: Any) -> None:
        return None

    executor = AgentHubExecutor(complete=crash, agent_loader=agent, tool_provisioner=tools, transcript_writer=write)
    result = await executor.run(packet(), MODEL, worktree, tmp_path, on_event)
    assert result.status == "failed" and (result.error or "").startswith("agent_hub_error")
    (saved,) = transcripts
    assert list(saved.turns) == [turn] and tool_text(saved.tool_results["t1"]) == "wrote 3 bytes"
    assert saved.error == result.error

    events: list[tuple[str, Any]] = []

    async def store_event(_db, _sid, event_type, **kw):
        events.append((event_type, kw.get("content")))

    async def noop(*_a: Any, **_k: Any) -> None:
        return None

    patch = pytest.MonkeyPatch()
    patch.setattr(agent_hub_transcript, "store_event", store_event)
    patch.setattr(agent_hub_transcript, "log_token_usage", noop)
    patch.setattr(agent_hub_transcript, "lock_session_event_ingestion", noop)
    try:
        await record_transcript(FakeDb(), saved)
    finally:
        patch.undo()
    assert [e[0] for e in events] == ["system_message", "user_message", "tool_use", "tool_result", "error"]
    assert (events[-1][1] or "").startswith("agent_hub_error")


async def test_a_run_past_the_old_hour_limit_is_not_ended(worktree, tmp_path) -> None:
    """Two hours pass on the loop clock while the model works; nothing in the executor ends the attempt for it."""

    from .support import loop_clock

    async def agent(_slug: str) -> Agent:
        return Agent()

    async def tools(_slug: str, _project: str) -> list[dict[str, Any]]:
        return PROVISIONED

    async def write(_transcript: Transcript) -> None:
        return None

    async def on_event(_event: Any) -> None:
        return None

    with loop_clock() as clock:
        async def slow(**_kw: Any) -> Any:
            clock.jump(2 * 3600)
            await asyncio.sleep(0.05)
            return internal([assistant([TextContent(text=HANDOFF)])])

        executor = AgentHubExecutor(complete=slow, agent_loader=agent, tool_provisioner=tools, transcript_writer=write)
        result = await executor.run(packet(), MODEL, worktree, tmp_path, on_event)
    assert result.status == "completed" and result.error is None


async def test_a_cancelled_attempt_aborts_its_provider_request_and_keeps_its_transcript(worktree, tmp_path) -> None:
    """Cancelling the step sets the abort signal handed to the provider (else the request keeps running and billing)."""

    seen: dict[str, Any] = {}
    transcripts: list[Transcript] = []
    started = asyncio.Event()

    async def hang(**kw: Any) -> Any:
        seen["signal"] = kw["signal"]
        started.set()
        await asyncio.Event().wait()

    async def write(transcript: Transcript) -> None:
        transcripts.append(transcript)

    async def agent(_slug: str) -> Agent:
        return Agent()

    async def tools(_slug: str, _project: str) -> list[dict[str, Any]]:
        return PROVISIONED

    async def on_event(_event: Any) -> None:
        return None

    executor = AgentHubExecutor(complete=hang, agent_loader=agent, tool_provisioner=tools, transcript_writer=write)
    task = asyncio.create_task(executor.run(packet(), MODEL, worktree, tmp_path, on_event))
    await started.wait()
    assert not seen["signal"].is_set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert seen["signal"].is_set()
    # The prompt was saved as soon as the step started; the cancel adds the final save.
    assert [t.error for t in transcripts] == [None, "cancelled"]


async def test_loop_events_become_phases_for_the_run_view(worktree, tmp_path) -> None:
    from .support import recording_live

    call = ToolCall(id="t1", name="write_file", arguments={"path": "hello.txt"})
    turn = assistant([call], "toolUse")
    events = [
        Event("start"),
        Event("thinking_delta"),
        Event("text_delta"),
        Event("toolcall_end", tool_call=call),
        Event("done", message=turn),
        Event("tool_run_start", tool_call=call),
        Event("tool_run_complete", tool_call=call, result=tool_result(call, "ok")),
        Event("turn_retry", reason="stream stalled"),
        Event("thinking_delta"),
        Event("done", message=assistant([TextContent(text=HANDOFF)])),
    ]
    with recording_live() as live:
        await run(worktree, tmp_path, [turn, assistant([TextContent(text=HANDOFF)])], loop_events=events)
    assert live.history == [
        "waiting", "thinking", "writing", "tool:write_file", "waiting", "tool:write_file", "waiting",
        "provider_retry", "thinking", "waiting",
    ]
    assert live.last_event_at is not None


def metric_turn(retries: list[dict[str, Any]]) -> AssistantMessage:
    from app.llm.utils.request_metrics import record_request_metrics

    message = assistant([TextContent(text="ok")])
    record_request_metrics(
        message, max_gap_s=41.5, keepalives=3, total_s=95.0, outcome="ok", retries=len(retries), retry_log=retries
    )
    return message


async def test_record_transcript_is_history_not_activity(monkeypatch) -> None:
    """Like a native transcript, it must not touch the sessions or copy events onto the run (that reverses the
    engine's lock order against a step settling, and moves last-active time on a finished attempt)."""

    from app.services.event_storage import _history_only

    stored: list[bool] = []

    async def store_event(_db, _session_id, _event_type, **_kw):
        stored.append(_history_only.get())

    async def log_usage(*_a, **_kw):
        return None

    async def lock(_db, _session_id):
        return None

    monkeypatch.setattr(agent_hub_transcript, "store_event", store_event)
    monkeypatch.setattr(agent_hub_transcript, "log_token_usage", log_usage)
    monkeypatch.setattr(agent_hub_transcript, "lock_session_event_ingestion", lock)
    transcript = Transcript(
        "attempt-1", "coder", MODEL, input_messages=[{"role": "user", "content": "goal"}],
        turns=[assistant([TextContent(text="done")])],
    )
    await record_transcript(FakeDb(), transcript)
    assert stored and all(stored)
    assert _history_only.get() is False  # and only for the write


async def test_record_transcript_saves_each_turns_request_record_once(monkeypatch) -> None:
    """The workflow path persists the same ``model_request`` audit and re-send events a /complete request does."""

    from app.api.complete import request_metrics

    events: list[dict[str, Any]] = []

    async def store_event(_db, session_id, event_type, **kw):
        events.append({"session_id": session_id, "type": event_type, **kw})

    async def noop(*_a: Any, **_k: Any) -> None:
        return None

    for module in (agent_hub_transcript, request_metrics):
        monkeypatch.setattr(module, "store_event", store_event)
    monkeypatch.setattr(agent_hub_transcript, "log_token_usage", noop)
    monkeypatch.setattr(agent_hub_transcript, "lock_session_event_ingestion", noop)
    retried = metric_turn([{"reason": "stream ended early", "delay_s": 2.0}])
    plain = assistant([TextContent(text="no record")])  # a turn whose provider recorded nothing keeps loop retries
    transcript = Transcript(
        "attempt-1", "coder", MODEL, input_messages=[{"role": "user", "content": "goal"}],
        turns=[retried, plain], retries=[(0, "stream ended early"), (1, "stalled")],
    )
    await record_transcript(FakeDb(), transcript)
    audits = [e for e in events if e["type"] == "tool_audit"]
    assert len(audits) == 1 and audits[0]["tool_name"] == "model_request"
    assert audits[0]["tool_output"]["max_gap_s"] == 41.5 and audits[0]["tool_output"]["keepalives"] == 3
    assert audits[0]["session_id"] == "attempt-1" and audits[0]["agent_id"] == "coder"
    retries = [e["content"] for e in events if e["type"] == "error"]
    assert retries == ["turn_retry: stream ended early", "turn_retry: stalled"]  # once each, never twice


@pytest.mark.parametrize("module", ["engine", "schemas"])
def test_workflow_modules_import_first_in_a_fresh_worker(module: str) -> None:
    """The worker imports the engine on its first advance, before anything has loaded app.api (whose package
    init imports the workflow routes, which import the engine): that order must not be a circular import."""

    done = subprocess.run(
        ["python", "-c", f"import app.services.workflow_runs.{module}"],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parents[3], check=False,
    )
    assert done.returncode == 0, done.stderr[-600:]


async def test_the_cost_basis_follows_the_models_provider_for_agent_hub_as_for_pi(worktree, tmp_path) -> None:
    from app.services.workflow_runs.executor_common import load_defaults
    from app.services.workflow_runs.usage import harness_basis

    model = "opencode-go/deepseek-v4.1-flash"
    turns = [assistant([TextContent(text=HANDOFF)], model="deepseek-v4.1-flash", provider="opencode-go")]
    result, _ = await run(worktree, tmp_path, turns, model=model)
    from app.constants.catalog import get_model_entry

    entry = get_model_entry(model)
    assert entry is not None
    pi_basis = harness_basis(entry.provider, load_defaults()["usage"])
    assert result.usage["cost_basis"] == pi_basis == "subscription_equiv"
    # The adapter's spelling of the served model is the catalog id, so it is not shown as a switch.
    assert result.served_models == [model]


async def test_each_turn_and_tool_result_is_saved_while_the_attempt_is_still_running(worktree, tmp_path) -> None:
    """The step's chat fills in live: the prompt first, then every finished turn, then every tool result."""

    call = ToolCall(id="t1", name="write_file", arguments={"path": "hello.txt"})
    first = assistant([call], "toolUse")
    saved: list[Transcript] = []
    seen = asyncio.Event()
    release = asyncio.Event()
    state = {"returned": False}

    async def write(transcript: Transcript) -> None:
        saved.append(transcript)
        seen.set()

    async def complete(**kw: Any) -> Any:
        await seen.wait()  # the prompt is saved before the first model turn is even finished
        assert [len(t.turns) for t in saved] == [0] and saved[0].input_messages
        seen.clear()
        kw["on_loop_event"](Event("done", message=first))
        await seen.wait()
        assert list(saved[-1].turns) == [first] and not saved[-1].tool_results  # the call is visible before it ran
        seen.clear()
        kw["on_loop_event"](Event("tool_run_complete", tool_call=call, result=tool_result(call, "wrote 3 bytes")))
        await seen.wait()
        assert tool_text(saved[-1].tool_results["t1"]) == "wrote 3 bytes"
        assert not state["returned"]  # all of it while the loop is still running
        await release.wait()
        state["returned"] = True
        return internal([first, assistant([TextContent(text=HANDOFF)])])

    async def agent(_slug: str) -> Agent:
        return Agent()

    async def tools(_slug: str, _project: str) -> list[dict[str, Any]]:
        return PROVISIONED

    async def on_event(_event: Any) -> None:
        return None

    executor = AgentHubExecutor(complete=complete, agent_loader=agent, tool_provisioner=tools, transcript_writer=write)
    task = asyncio.create_task(executor.run(packet(), MODEL, worktree, tmp_path, on_event))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if len(saved) >= 3:
            break
    assert len(saved) >= 3 and not task.done()
    release.set()
    result = await task
    assert result.status == "completed"
    assert len(saved[-1].turns) == 2  # the final save carries the closing turn too
