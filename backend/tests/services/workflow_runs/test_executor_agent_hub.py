"""Agent Hub step executor: the completion path is faked, the mapping to StepResult is the unit."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from app.api.complete.types import CompletionInternalResult
from app.llm.types import AssistantMessage, TextContent, ToolCall, Usage
from app.llm.utils.outcomes import ProviderOutcome, record_outcome
from app.services.workflow_runs.executor_agent_hub import AgentHubExecutor
from app.services.workflow_runs.executors import get_executor
from app.services.workflow_runs.packet import AttemptRef, GitState, build_packet

MODEL = "claude-opus-5-5"
HANDOFF = '```handoff\n{"summary": "wrote hello.txt", "decisions": [], "files": ["hello.txt"], "open_questions": []}\n```'


@dataclass
class Agent:
    temperature: float = 0.3
    thinking_level: str | None = "high"


def assistant(content: list[Any], stop: str = "stop", *, model: str = MODEL, **kwargs: Any) -> AssistantMessage:
    usage = Usage(input=10, output=5, cache_read=100, cache_write=20, total_tokens=135)
    usage.cost.total = 0.01
    return AssistantMessage(
        content=content, api="claude-code-cli", provider="claude", model=model, usage=usage,
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
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "base"]):
        subprocess.run(["git", *args], cwd=path, check=True, env=env)
    return path


def packet(test_hooks: dict[str, Any] | None = None, level: str | None = None):
    base = build_packet(
        run_goal="goal", step_key="implement", instructions="create hello.txt", acceptance=[],
        git=GitState(), prior_steps=[], run_dir="/run", context_window=100_000, budget_fraction=0.25,
    )
    return replace(base, test_hooks=test_hooks, level=level, attempt=AttemptRef("attempt-1", "run-1", "proj", "coder"))


PROVISIONED = [{"name": "write_file"}]


async def run(worktree: Path, tmp_path: Path, messages: list[AssistantMessage], provisioned=None, **kwargs: Any):
    calls: list[dict[str, Any]] = []

    async def complete(**kw: Any) -> CompletionInternalResult:
        calls.append(kw)
        return internal(messages)

    async def agent(_slug: str) -> Agent:
        return Agent()

    async def tools(_slug: str, _project: str) -> list[dict[str, Any]]:
        return PROVISIONED if provisioned is None else provisioned

    executor = AgentHubExecutor(complete=complete, agent_loader=agent, tool_provisioner=tools)

    async def on_event(_event: Any) -> None:
        return None

    result = await executor.run(packet(**kwargs), MODEL, worktree, tmp_path, on_event)
    return result, calls


def test_registered_under_its_kind() -> None:
    assert isinstance(get_executor("agent_hub"), AgentHubExecutor)


async def test_runs_the_tool_loop_on_the_worktree_with_the_attempt_session(worktree, tmp_path) -> None:
    call = ToolCall(id="t1", name="write_file", arguments={"path": "hello.txt"})
    turns = [assistant([call], "toolUse"), assistant([TextContent(text=f"Done.\n{HANDOFF}")])]
    result, calls = await run(worktree, tmp_path, turns)
    kw = calls[0]
    assert kw["tools"] == [{"name": "write_file"}]
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
    only = [{"name": "bash"}, {"name": "manage_tasks"}]
    _, calls = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], provisioned=only)
    assert [t["name"] for t in calls[0]["tools"]] == ["bash"]
    assert "- read_file" not in calls[0]["messages"][0]["content"]
    other = [{"name": "manage_tasks"}]
    _, calls = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], provisioned=other)
    assert calls[0]["tools"] == other and [m["role"] for m in calls[0]["messages"]] == ["user"]


async def test_unknown_level_fails_before_any_model_call(worktree, tmp_path) -> None:
    result, calls = await run(worktree, tmp_path, [assistant([TextContent(text=HANDOFF)])], level="huge")
    assert result.status == "failed" and "unknown level" in result.error and calls == []
