"""Parallel execution of read-only tool calls in the unified tool loop."""

from __future__ import annotations

import asyncio

import pytest

from app.api.complete.tool_provisioner import build_direct_tool_runner
from app.llm.providers.faux import faux_assistant_message, faux_tool_call, register_faux_provider
from app.llm.tool_loop import ToolRunComplete, ToolRunError, ToolRunStart
from app.llm.tool_loop import run as run_loop
from app.llm.types import Context, TextContent, ToolCall, ToolResultMessage, UserMessage


def _result(call: ToolCall, text: str, *, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=call.id, tool_name=call.name, content=[TextContent(text=text)], is_error=is_error, timestamp=0
    )


async def _drive(calls, run_tool, **kwargs):
    reg = register_faux_provider()
    try:
        reg.set_responses([faux_assistant_message(calls, stop_reason="toolUse"), faux_assistant_message("done")])
        model = reg.get_model()
        assert model is not None
        context = Context(messages=[UserMessage(content="go", timestamp=0)])
        events = [e async for e in run_loop(model, context, run_tool, **kwargs)]
        return events, context
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_parallel_safe_calls_overlap_and_results_keep_call_order() -> None:
    running = 0
    peak = 0

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        # The first call finishes last, so completion order differs from call order.
        await asyncio.sleep(0.05 if call.id == "a" else 0.01)
        running -= 1
        return _result(call, f"out-{call.id}")

    calls = [faux_tool_call("read_file", {"path": p}, id=p) for p in ("a", "b", "c")]
    events, context = await _drive(calls, run_tool, is_parallel_safe=lambda c: True)

    assert peak == 3
    results = [m for m in context.messages if isinstance(m, ToolResultMessage)]
    assert [r.tool_call_id for r in results] == ["a", "b", "c"]
    completes = [e.tool_call.id for e in events if isinstance(e, ToolRunComplete)]
    assert completes == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_mutating_calls_stay_serial_and_split_parallel_runs() -> None:
    log: list[str] = []

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        log.append(f"start-{call.id}")
        await asyncio.sleep(0.01)
        log.append(f"end-{call.id}")
        return _result(call, "ok")

    calls = [
        faux_tool_call("read_file", {}, id="r1"),
        faux_tool_call("edit_file", {}, id="w"),
        faux_tool_call("read_file", {}, id="r2"),
        faux_tool_call("read_file", {}, id="r3"),
    ]
    await _drive(calls, run_tool, is_parallel_safe=lambda c: c.name == "read_file")

    assert log[:4] == ["start-r1", "end-r1", "start-w", "end-w"]  # the edit never overlaps a read
    assert log[4:6] == ["start-r2", "start-r3"]  # trailing reads share a batch


@pytest.mark.asyncio
async def test_default_loop_is_serial() -> None:
    running = 0
    peak = 0

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return _result(call, "ok")

    calls = [faux_tool_call("read_file", {}, id=str(i)) for i in range(3)]
    await _drive(calls, run_tool)

    assert peak == 1


@pytest.mark.asyncio
async def test_one_parallel_failure_becomes_an_error_result_without_hiding_the_others() -> None:
    async def run_tool(call: ToolCall) -> ToolResultMessage:
        if call.id == "bad":
            raise RuntimeError("boom")
        return _result(call, "fine")

    calls = [faux_tool_call("read_file", {}, id=i) for i in ("ok1", "bad", "ok2")]
    events, context = await _drive(calls, run_tool, is_parallel_safe=lambda c: True)

    assert [type(e).__name__ for e in events if isinstance(e, ToolRunStart | ToolRunComplete | ToolRunError)] == [
        "ToolRunStart", "ToolRunStart", "ToolRunStart", "ToolRunComplete", "ToolRunError", "ToolRunComplete",
    ]
    results = {m.tool_call_id: m for m in context.messages if isinstance(m, ToolResultMessage)}
    assert results["bad"].is_error and "boom" in results["bad"].content[0].text
    assert not results["ok1"].is_error and not results["ok2"].is_error


def test_direct_runner_marks_only_read_only_tools_parallel_safe() -> None:
    runner = build_direct_tool_runner(working_dir=None, project_id=None, session_id=None, agent_slug=None)
    safe = runner.is_parallel_safe  # type: ignore[attr-defined]

    assert safe(faux_tool_call("read_file", {}, id="1"))
    assert safe(faux_tool_call("search_scratch_context", {}, id="2"))
    for name in ("bash", "write_file", "edit_file", "batch_execute", "consult_agent", "dispatch_agent", "manage_tasks"):
        assert not safe(faux_tool_call(name, {}, id="3"))


def _write_call(name: str, path: str, id: str) -> ToolCall:
    return faux_tool_call(name, {"path": path}, id=id)


@pytest.mark.asyncio
async def test_writes_to_different_files_overlap_and_a_repeat_or_other_call_splits_the_batch() -> None:
    log: list[str] = []

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        log.append(f"start-{call.id}")
        await asyncio.sleep(0.01)
        log.append(f"end-{call.id}")
        return _result(call, "ok")

    calls = [
        _write_call("write_file", "a.py", "w1"),
        _write_call("edit_file", "b.py", "w2"),
        _write_call("write_file", "a.py", "w3"),  # same file as w1: waits for the batch before it
        faux_tool_call("bash", {"command": "true"}, id="sh"),
        _write_call("write_file", "c.py", "w4"),
    ]
    await _drive(calls, run_tool, file_target=lambda c: c.arguments.get("path"), max_file_batch=4)

    assert log[:2] == ["start-w1", "start-w2"]  # different files share a batch
    assert log.index("start-w3") > log.index("end-w1") and log.index("start-w3") > log.index("end-w2")
    assert log.index("start-sh") > log.index("end-w3") and log.index("start-w4") > log.index("end-sh")


@pytest.mark.asyncio
async def test_file_writes_stay_serial_without_a_target_and_respect_the_batch_width() -> None:
    running = 0
    peak = 0

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return _result(call, "ok")

    calls = [_write_call("write_file", f"f{i}.py", f"w{i}") for i in range(5)]
    await _drive(calls, run_tool)
    assert peak == 1

    peak = 0
    await _drive(calls, run_tool, file_target=lambda c: c.arguments["path"], max_file_batch=2)
    assert peak == 2


@pytest.mark.asyncio
async def test_a_read_never_shares_a_batch_with_a_write() -> None:
    log: list[str] = []

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        log.append(f"start-{call.id}")
        await asyncio.sleep(0.01)
        log.append(f"end-{call.id}")
        return _result(call, "ok")

    calls = [_write_call("write_file", "a.py", "w"), faux_tool_call("read_file", {"path": "a.py"}, id="r")]
    await _drive(
        calls, run_tool, is_parallel_safe=lambda c: c.name == "read_file",
        file_target=lambda c: c.arguments["path"] if c.name == "write_file" else None, max_file_batch=4,
    )
    assert log == ["start-w", "end-w", "start-r", "end-r"]


def test_direct_runner_keys_single_file_writes_by_resolved_path(tmp_path) -> None:
    runner = build_direct_tool_runner(working_dir=str(tmp_path), project_id=None, session_id=None, agent_slug=None)
    target = runner.file_target  # type: ignore[attr-defined]

    assert target(_write_call("write_file", "a.py", "1")) == target(_write_call("edit_file", str(tmp_path / "a.py"), "2"))
    assert target(_write_call("write_file", "a.py", "1")) != target(_write_call("write_file", "sub/a.py", "3"))
    assert target(_write_call("write_file", "x/../a.py", "4")) == target(_write_call("write_file", "a.py", "5"))
    for call in (faux_tool_call("bash", {"command": "true"}, id="6"), faux_tool_call("write_file", {}, id="7")):
        assert target(call) is None
    assert runner.max_file_batch > 1  # type: ignore[attr-defined]
