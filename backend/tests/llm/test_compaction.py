"""Context compaction in the tool loop: when it fires, where it cuts, what it keeps, what it records."""

from __future__ import annotations

import pytest

from app.llm.compaction import (
    CompactionFailed,
    CompactionPolicy,
    Compactor,
    SummaryRequest,
    SummaryResult,
    estimate_context_tokens,
    find_cut_point,
    message_tokens,
)
from app.llm.providers.faux import (
    FauxModelDefinition,
    RegisterFauxProviderOptions,
    faux_assistant_message,
    faux_tool_call,
    register_faux_provider,
)
from app.llm.tool_loop import ContextCompacted
from app.llm.tool_loop import run as run_loop
from app.llm.types import (
    AssistantMessage,
    Context,
    DoneEvent,
    ErrorEvent,
    TextContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)

PAD = "x" * 400  # 100 estimated tokens


def policy(window: int = 1000, reserve: int = 200, keep: int = 250, **kw) -> CompactionPolicy:
    return CompactionPolicy(
        context_window=window, reserve_tokens=reserve, keep_recent_tokens=keep, tool_result_chars=50,
        read_tools=frozenset({"read_file"}), write_tools=frozenset({"edit_file"}), **kw,
    )


def user(text: str) -> UserMessage:
    return UserMessage(content=text, timestamp=0)


def assistant(text: str = "", calls: list[ToolCall] | None = None, usage: Usage | None = None) -> AssistantMessage:
    content: list = [TextContent(text=text)] if text else []
    content += calls or []
    return AssistantMessage(
        content=content, api="faux", provider="faux", model="faux-1", usage=usage or Usage(),
        stop_reason="toolUse" if calls else "stop", timestamp=0,
    )


def result(call: ToolCall, text: str = PAD) -> ToolResultMessage:
    return ToolResultMessage(tool_call_id=call.id, tool_name=call.name, content=[TextContent(text=text)], is_error=False, timestamp=0)


def tool_turn(index: int, name: str = "read_file", path: str | None = None) -> list:
    call = ToolCall(id=f"c{index}", name=name, arguments={"path": path or f"/f{index}"})
    return [assistant(f"step {index}", [call]), result(call)]


def history(turns: int) -> Context:
    messages: list = [user("the task")]
    for index in range(turns):
        messages += tool_turn(index)
    return Context(messages=messages, system_prompt="system rules")


class Recorder:
    def __init__(self, text: str = "SUMMARY", fail: Exception | None = None) -> None:
        self.requests: list[SummaryRequest] = []
        self.text, self.fail = text, fail

    async def __call__(self, request: SummaryRequest) -> SummaryResult:
        self.requests.append(request)
        if self.fail:
            raise self.fail
        return SummaryResult(text=self.text, model="fake-summarizer", input_tokens=500, output_tokens=40, cost_usd=0.001)


# --- cut point ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("keep", [1, 50, 100, 150, 220, 330, 1000])
def test_the_cut_never_separates_a_tool_call_from_its_results(keep: int) -> None:
    messages = history(6).messages
    # a parallel turn: one assistant message with two calls, then both results
    calls = [ToolCall(id="p1", name="read_file", arguments={"path": "/a"}), ToolCall(id="p2", name="read_file", arguments={"path": "/b"})]
    messages += [assistant("both", calls), result(calls[0]), result(calls[1]), assistant("done")]

    cut = find_cut_point(messages, 1, keep)

    assert cut == 1 or not isinstance(messages[cut], ToolResultMessage)
    kept_ids = {r.tool_call_id for r in messages[cut:] if isinstance(r, ToolResultMessage)}
    kept_calls = {b.id for m in messages[cut:] if isinstance(m, AssistantMessage) for b in m.content if isinstance(b, ToolCall)}
    assert kept_ids <= kept_calls  # no kept result lost its call
    summarized_calls = {b.id for m in messages[1:cut] if isinstance(m, AssistantMessage) for b in m.content if isinstance(b, ToolCall)}
    assert not summarized_calls & kept_ids  # no summarized call has a kept result


def test_results_larger_than_the_budget_keep_the_assistant_message_that_made_the_calls() -> None:
    call = ToolCall(id="big", name="read_file", arguments={"path": "/big"})
    messages = [user("task"), assistant("old"), user("more"), assistant("calls", [call]), result(call, "y" * 8000)]

    cut = find_cut_point(messages, 1, 100)

    assert isinstance(messages[cut], AssistantMessage) and messages[cut].content[-1] is call


def test_nothing_is_cut_when_the_tail_never_reaches_the_budget() -> None:
    messages = history(2).messages
    assert find_cut_point(messages, 1, 10_000) == 1


# --- size ---------------------------------------------------------------------------------------------------------


def test_the_estimate_prefers_the_last_provider_usage_plus_newer_messages() -> None:
    context = history(2)
    context.messages[2] = assistant("measured", usage=Usage(input=700, cache_read=100, output=50))
    context.messages.append(user("z" * 80))  # 20 tokens

    trailing = sum(message_tokens(m) for m in context.messages[3:])
    assert estimate_context_tokens(context) == (850 + trailing, "usage")
    assert estimate_context_tokens(context, trusted_from=len(context.messages))[1] == "estimate"


# --- compaction ---------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_under_the_threshold_nothing_happens() -> None:
    summarize = Recorder()
    context = history(2)  # about 270 tokens against a threshold of 800

    assert await Compactor(policy(), summarize).compact_if_needed(context) is None
    assert not summarize.requests and len(context.messages) == 5


@pytest.mark.asyncio
async def test_the_summary_replaces_the_prefix_and_keeps_the_system_prompt_the_task_and_the_recent_tail() -> None:
    summarize = Recorder()
    context = history(10)  # about 1250 tokens against a threshold of 800
    original = list(context.messages)

    record = await Compactor(policy(), summarize).compact_if_needed(context)

    assert record is not None and record.status == "ok"
    assert context.system_prompt == "system rules"
    assert context.messages[0] is original[0]  # the task
    summary = context.messages[1]
    assert isinstance(summary, UserMessage) and "SUMMARY" in summary.content
    assert "<read-files>" in summary.content and "/f0" in summary.content  # file ops of the summarized calls
    kept = context.messages[2:]
    assert kept == original[len(original) - len(kept):]  # the tail is the original messages, untouched
    assert kept and not isinstance(kept[0], ToolResultMessage)
    assert record.messages_summarized == len(original) - 1 - len(kept)
    assert record.messages_kept == len(kept)
    assert record.tokens_after < record.tokens_before
    assert record.summarizer_model == "fake-summarizer" and record.cost_usd == 0.001
    assert "step 0" in summarize.requests[0].transcript and "more characters truncated" in summarize.requests[0].transcript  # results are clipped


@pytest.mark.asyncio
async def test_the_same_prefix_is_not_summarized_twice() -> None:
    summarize = Recorder()
    compactor = Compactor(policy(), summarize)
    context = history(10)
    assert await compactor.compact_if_needed(context) is not None
    after = list(context.messages)

    assert await compactor.compact_if_needed(context) is None  # nothing new since
    assert context.messages == after and len(summarize.requests) == 1

    # New work after it folds the standing summary and what came since into one updated summary.
    for index in range(10, 18):
        context.messages += tool_turn(index, name="edit_file", path=f"/f{index}")
    record = await compactor.compact_if_needed(context)

    assert record is not None and len(summarize.requests) == 2
    assert summarize.requests[1].previous_summary == "SUMMARY"
    assert "step 0" not in summarize.requests[1].transcript  # the first prefix is not read again
    assert sum("<summary>" in str(m.content) for m in context.messages if isinstance(m, UserMessage)) == 1
    assert "<modified-files>" in context.messages[1].content and "/f0" in context.messages[1].content


@pytest.mark.asyncio
async def test_usage_measured_before_a_compaction_is_not_trusted_after_it() -> None:
    compactor = Compactor(policy(), Recorder())
    context = history(10)
    context.messages[-2] = assistant("measured", [ToolCall(id="c9", name="read_file", arguments={"path": "/f9"})], Usage(input=5000))
    assert await compactor.compact_if_needed(context) is not None

    assert estimate_context_tokens(context, compactor._trusted_from)[1] == "estimate"
    assert await compactor.compact_if_needed(context) is None  # the stale 5000 does not trigger another


@pytest.mark.asyncio
async def test_a_failing_summarizer_raises_and_leaves_the_history_alone() -> None:
    context = history(10)
    original = list(context.messages)

    with pytest.raises(CompactionFailed, match="boom"):
        await Compactor(policy(), Recorder(fail=RuntimeError("boom"))).compact_if_needed(context)
    with pytest.raises(CompactionFailed, match="no text"):
        await Compactor(policy(), Recorder(text="  ")).compact_if_needed(context)

    assert context.messages == original


# --- in the loop --------------------------------------------------------------------------------------------------


def _faux(window: int):
    return register_faux_provider(
        RegisterFauxProviderOptions(models=[FauxModelDefinition(id="faux-small", context_window=window)])
    )


@pytest.mark.asyncio
async def test_the_loop_compacts_mid_run_and_carries_on() -> None:
    reg = _faux(1000)
    try:
        calls = [faux_tool_call("read_file", {"path": f"/f{i}"}, id=f"c{i}") for i in range(12)]
        reg.set_responses([faux_assistant_message([c], stop_reason="toolUse") for c in calls] + [faux_assistant_message("all done")])
        model = reg.get_model()
        assert model is not None
        summarize = Recorder()
        compactor = Compactor(policy(window=model.context_window), summarize)

        async def run_tool(call: ToolCall) -> ToolResultMessage:
            return result(call)

        context = Context(messages=[user("the task")], system_prompt="system rules")
        events = [e async for e in run_loop(model, context, run_tool, compactor=compactor)]

        compacted = [e for e in events if isinstance(e, ContextCompacted)]
        assert compacted and compacted[0].record.tokens_before > compacted[0].record.threshold
        finals = [e for e in events if isinstance(e, DoneEvent)]
        assert "".join(b.text for b in finals[-1].message.content if isinstance(b, TextContent)) == "all done"
        assert len(summarize.requests) == len(compacted)
        # The provider calls after a compaction carry it on their request metrics; earlier ones do not.
        marked = [e.message for e in finals if (e.message.diagnostics or [])]
        from app.llm.utils.request_metrics import request_metrics_of

        assert any((request_metrics_of(m) or {}).get("compactions") for m in marked)
        assert context.messages[0].content == "the task"
        # every tool result that survives still has its call
        calls_kept = {b.id for m in context.messages if isinstance(m, AssistantMessage) for b in m.content if isinstance(b, ToolCall)}
        assert {m.tool_call_id for m in context.messages if isinstance(m, ToolResultMessage)} <= calls_kept
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_a_summary_that_cannot_be_made_ends_the_loop_with_an_explicit_error_and_no_model_call() -> None:
    reg = _faux(1000)
    try:
        reg.set_responses([faux_assistant_message("never asked")])
        model = reg.get_model()
        assert model is not None
        context = history(10)
        before = list(context.messages)

        async def run_tool(call: ToolCall) -> ToolResultMessage:
            return result(call)

        compactor = Compactor(policy(window=model.context_window), Recorder(fail=RuntimeError("summarizer down")))
        events = [e async for e in run_loop(model, context, run_tool, compactor=compactor)]

        errors = [e for e in events if isinstance(e, ErrorEvent)]
        assert len(errors) == 1
        assert "context_compaction_failed: RuntimeError: summarizer down" in (errors[0].error.error_message or "")
        assert reg.get_pending_response_count() == 1  # the provider was never called
        assert context.messages[: len(before)] == before  # nothing was dropped
        from app.llm.utils.request_metrics import request_metrics_of

        assert (request_metrics_of(errors[0].error) or {})["compactions"][0]["status"] == "failed"
    finally:
        reg.unregister()


def test_message_tokens_counts_arguments_and_text() -> None:
    assert message_tokens(user("a" * 40)) == 10
    assert message_tokens(assistant("", [ToolCall(id="1", name="n", arguments={"path": "p" * 30})])) > 8


@pytest.mark.asyncio
async def test_the_stream_reports_the_compaction_as_a_context_compacted_event_before_the_answer() -> None:
    import json

    from app.api.complete.orchestrator import run_completion_stream
    from app.api.complete.sse_writer import SseWriter
    from app.api.complete.streaming import _emit_events
    from tests.api.stream_test_support import make_stream_ctx, patched_done_persistence

    reg = _faux(1000)
    try:
        reg.set_responses([faux_assistant_message("answer")])
        model = reg.get_model()
        assert model is not None
        context = history(10)

        async def run_tool(call: ToolCall) -> ToolResultMessage:
            return result(call)

        chunks: list[str] = []
        with patched_done_persistence():
            async for chunk in _emit_events(
                run_completion_stream(
                    model, context, execute_tools=True, run_tool=run_tool,
                    compactor=Compactor(policy(window=model.context_window), Recorder()),
                ),
                SseWriter(session_id="s"), make_stream_ctx("s"), [""],
            ):
                chunks.append(chunk)

        payloads = [json.loads(c.removeprefix("data: ")) for c in chunks]
        assert [p["type"] for p in payloads] == ["context_compacted", "content", "done"]
        event = payloads[0]
        assert event["status"] == "ok" and event["summarizer_model"] == "fake-summarizer"
        assert event["tokens_before"] > event["tokens_after"] > 0
    finally:
        reg.unregister()


def test_the_policy_takes_the_catalog_window_and_the_configured_sizes(monkeypatch) -> None:
    from app.api.complete.context_compaction import build_loop_compactor
    from app.config import settings

    reg = _faux(64_000)
    try:
        model = reg.get_model()
        assert model is not None
        monkeypatch.setattr(settings, "llm_compaction_reserve_tokens", 4_000)
        monkeypatch.setattr(settings, "llm_compaction_keep_recent_tokens", 9_000)
        monkeypatch.setattr(settings, "llm_compaction_window_overrides", {})

        compactor = build_loop_compactor(model)
        assert compactor is not None
        policy_ = compactor.policy
        assert (policy_.context_window, policy_.threshold, policy_.keep_recent_tokens) == (64_000, 60_000, 9_000)

        monkeypatch.setattr(settings, "llm_compaction_window_overrides", {model.id: 6_000})
        overridden = build_loop_compactor(model)
        assert overridden is not None and overridden.policy.threshold == 2_000  # a data override replaces the catalog's window

        monkeypatch.setattr(settings, "llm_compaction_enabled", False)
        assert build_loop_compactor(model) is None
    finally:
        reg.unregister()
