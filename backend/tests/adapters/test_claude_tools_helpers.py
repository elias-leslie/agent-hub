from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock

import pytest

from app.adapters.claude_tools_helpers import _close_internal_query, _stream_sdk_messages


class ResultMessage:
    pass


@pytest.mark.asyncio
async def test_stream_sdk_messages_closes_after_result_message(monkeypatch: pytest.MonkeyPatch) -> None:
    yielded = []
    iterator_holder: dict[str, object] = {}

    class ClosingIterator:
        def __init__(self) -> None:
            self.closed = False
            self._step = 0

        def __aiter__(self) -> ClosingIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                yielded.append("assistant")
                return types.SimpleNamespace(content=[], subtype=None)
            if self._step == 1:
                self._step += 1
                yielded.append("result")
                return ResultMessage()
            yielded.append("after-result")
            raise AssertionError("stream should be closed immediately after ResultMessage")

        async def aclose(self) -> None:
            self.closed = True

    def fake_query(*, prompt, options):
        iterator = ClosingIterator()
        iterator_holder["iterator"] = iterator
        return iterator

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", object(), "claude"):
        seen.append((type(message).__name__, session_id))

    iterator = iterator_holder["iterator"]
    assert seen == [("SimpleNamespace", None), ("ResultMessage", None)]
    assert yielded == ["assistant", "result"]
    assert iterator.closed is True


@pytest.mark.asyncio
async def test_stream_sdk_messages_synthesizes_result_when_stream_ends_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iterator_holder: dict[str, object] = {}

    class ClosingIterator:
        def __init__(self) -> None:
            self.closed = False
            self._step = 0

        def __aiter__(self) -> ClosingIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                return types.SimpleNamespace(content=[], subtype=None)
            raise StopAsyncIteration

        async def aclose(self) -> None:
            self.closed = True

    def fake_query(*, prompt, options):
        iterator = ClosingIterator()
        iterator_holder["iterator"] = iterator
        return iterator

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", object(), "claude"):
        seen.append((type(message).__name__, session_id, getattr(message, "finish_reason", None)))

    iterator = iterator_holder["iterator"]
    assert seen == [("SimpleNamespace", None, None), ("ResultMessage", None, "end_turn")]
    assert iterator.closed is True


@pytest.mark.asyncio
async def test_stream_sdk_messages_synthesizes_end_turn_after_tool_result_without_budget_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosingIterator:
        def __init__(self) -> None:
            self._step = 0

        def __aiter__(self) -> ClosingIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                tool_use = types.SimpleNamespace(
                    type="tool_use",
                    id="tool-1",
                    name="Bash",
                    input={"command": "printf 'STEP 1\\n'"},
                )
                return types.SimpleNamespace(content=[tool_use], subtype=None)
            if self._step == 1:
                self._step += 1
                tool_result = types.SimpleNamespace(
                    type="tool_result",
                    tool_use_id="tool-1",
                    content="STEP 1\n",
                    is_error=False,
                )
                return types.SimpleNamespace(content=[tool_result], subtype=None)
            raise StopAsyncIteration

    def fake_query(*, prompt, options):
        return ClosingIterator()

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", object(), "claude"):
        seen.append((type(message).__name__, session_id, getattr(message, "finish_reason", None)))

    assert seen[-1] == ("ResultMessage", None, "end_turn")


@pytest.mark.asyncio
async def test_stream_sdk_messages_allows_slow_post_tool_progress_without_synthesizing_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowIterator:
        def __init__(self) -> None:
            self._step = 0

        def __aiter__(self) -> SlowIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                block = types.SimpleNamespace(
                    type="tool_result",
                    tool_use_id="tool-1",
                    content="ok",
                    is_error=False,
                )
                return types.SimpleNamespace(content=[block], subtype=None)
            if self._step == 1:
                self._step += 1
                await asyncio.sleep(0.01)
                return ResultMessage()
            raise StopAsyncIteration

    def fake_query(*, prompt, options):
        return SlowIterator()

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", object(), "claude"):
        seen.append((type(message).__name__, session_id))

    assert seen == [("SimpleNamespace", None), ("ResultMessage", None)]


@pytest.mark.asyncio
async def test_stream_sdk_messages_marks_empty_result_after_tool_result_as_end_turn_without_budget_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosingIterator:
        def __init__(self) -> None:
            self._step = 0

        def __aiter__(self) -> ClosingIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                tool_use = types.SimpleNamespace(
                    type="tool_use",
                    id="tool-1",
                    name="Bash",
                    input={"command": "printf 'STEP 1\\n'"},
                )
                return types.SimpleNamespace(content=[tool_use], subtype=None)
            if self._step == 1:
                self._step += 1
                tool_result = types.SimpleNamespace(
                    type="tool_result",
                    tool_use_id="tool-1",
                    content="STEP 1\n",
                    is_error=False,
                )
                return types.SimpleNamespace(content=[tool_result], subtype=None)
            if self._step == 2:
                self._step += 1
                return ResultMessage()
            raise StopAsyncIteration

    def fake_query(*, prompt, options):
        return ClosingIterator()

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", object(), "claude"):
        seen.append((type(message).__name__, session_id, getattr(message, "finish_reason", None)))

    assert seen[-1] == ("ResultMessage", None, "end_turn")


@pytest.mark.asyncio
async def test_stream_sdk_messages_prefers_native_stop_reason_over_budget_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosingIterator:
        def __init__(self) -> None:
            self._step = 0

        def __aiter__(self) -> ClosingIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                result = ResultMessage()
                result.stop_reason = "max_turns"
                result.num_turns = 2
                return result
            raise StopAsyncIteration

    def fake_query(*, prompt, options):
        return ClosingIterator()

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", types.SimpleNamespace(max_turns=4), "claude"):
        seen.append(
            (
                type(message).__name__,
                session_id,
                getattr(message, "finish_reason", None),
                getattr(message, "stop_reason", None),
            )
        )

    assert seen[-1] == ("ResultMessage", None, "max_turns", "max_turns")


@pytest.mark.asyncio
async def test_stream_sdk_messages_maps_error_max_turns_subtype_without_budget_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosingIterator:
        def __init__(self) -> None:
            self._step = 0

        def __aiter__(self) -> ClosingIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                result = ResultMessage()
                result.subtype = "error_max_turns"
                result.num_turns = 2
                return result
            raise StopAsyncIteration

    def fake_query(*, prompt, options):
        return ClosingIterator()

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", types.SimpleNamespace(max_turns=4), "claude"):
        seen.append(
            (
                type(message).__name__,
                session_id,
                getattr(message, "finish_reason", None),
                getattr(message, "stop_reason", None),
            )
        )

    assert seen[-1] == ("ResultMessage", None, "max_turns", "max_turns")


@pytest.mark.asyncio
async def test_stream_sdk_messages_marks_empty_result_at_budget_as_max_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosingIterator:
        def __init__(self) -> None:
            self._step = 0

        def __aiter__(self) -> ClosingIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                tool_use = types.SimpleNamespace(
                    type="tool_use",
                    id="tool-1",
                    name="Bash",
                    input={"command": "printf 'STEP 1\\n'"},
                )
                return types.SimpleNamespace(content=[tool_use], subtype=None)
            if self._step == 1:
                self._step += 1
                tool_result = types.SimpleNamespace(
                    type="tool_result",
                    tool_use_id="tool-1",
                    content="STEP 1\n",
                    is_error=False,
                )
                return types.SimpleNamespace(content=[tool_result], subtype=None)
            if self._step == 2:
                self._step += 1
                result = ResultMessage()
                result.num_turns = 4
                return result
            raise StopAsyncIteration

    def fake_query(*, prompt, options):
        return ClosingIterator()

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", types.SimpleNamespace(max_turns=4), "claude"):
        seen.append((type(message).__name__, session_id, getattr(message, "finish_reason", None)))

    assert seen[-1] == ("ResultMessage", None, "max_turns")


@pytest.mark.asyncio
async def test_stream_sdk_messages_emits_error_message_when_post_tool_progress_stalls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters import claude_tools_helpers as helpers

    class HangingIterator:
        def __init__(self) -> None:
            self._step = 0
            self._closed = False

        def __aiter__(self) -> HangingIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                block = types.SimpleNamespace(
                    type="tool_result",
                    tool_use_id="tool-1",
                    content="ok",
                    is_error=False,
                )
                return types.SimpleNamespace(content=[block], subtype=None)
            while not self._closed:
                await asyncio.Event().wait()
            raise StopAsyncIteration

        async def aclose(self) -> None:
            self._closed = True

    def fake_query(*, prompt, options):
        return HangingIterator()

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)
    monkeypatch.setattr(helpers, "_SDK_POST_TOOL_IDLE_TIMEOUT_SECONDS", 0.01)

    seen = []
    async for message, _session_id in _stream_sdk_messages("prompt", object(), "claude"):
        seen.append(type(message).__name__)

    assert seen == ["SimpleNamespace", "ErrorMessage"]


@pytest.mark.asyncio
async def test_stream_sdk_messages_closes_cleanly_when_consumer_stops_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iterator_holder: dict[str, object] = {}

    class ClosingIterator:
        def __init__(self) -> None:
            self.closed = False
            self._step = 0

        def __aiter__(self) -> ClosingIterator:
            return self

        async def __anext__(self):
            if self._step == 0:
                self._step += 1
                return types.SimpleNamespace(content=[], subtype=None)
            await asyncio.Event().wait()
            raise StopAsyncIteration

        async def aclose(self) -> None:
            self.closed = True

    def fake_query(*, prompt, options):
        iterator = ClosingIterator()
        iterator_holder["iterator"] = iterator
        return iterator

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    stream = _stream_sdk_messages("prompt", object(), "claude")
    first = await anext(stream)
    assert first[0].content == []
    await stream.aclose()

    iterator = iterator_holder["iterator"]
    assert iterator.closed is True


@pytest.mark.asyncio
async def test_stream_sdk_messages_does_not_reclose_after_natural_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters import claude_tools_helpers as helpers

    class InnerIter:
        def __init__(self) -> None:
            self.aclose_calls = 0
            self._done = False

        def __aiter__(self) -> InnerIter:
            return self

        async def __anext__(self):
            if self._done:
                raise StopAsyncIteration
            self._done = True
            return ResultMessage(), "sdk-session-1"

        async def aclose(self) -> None:
            self.aclose_calls += 1

    inner = InnerIter()
    monkeypatch.setattr(helpers, "_iterate_sdk_messages", lambda prompt, options, provider_name: inner)

    seen = []
    async for message, session_id in helpers._stream_sdk_messages("prompt", object(), "claude"):
        seen.append((type(message).__name__, session_id))

    assert seen == [("ResultMessage", "sdk-session-1")]
    assert inner.aclose_calls == 0


@pytest.mark.asyncio
async def test_stream_sdk_messages_closes_sdk_iterator_on_producer_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iterator_holder: dict[str, object] = {}

    class TaskAwareIterator:
        def __init__(self) -> None:
            self.owner_task: asyncio.Task | None = None
            self.closed_by: asyncio.Task | None = None
            self._step = 0

        def __aiter__(self) -> TaskAwareIterator:
            return self

        async def __anext__(self):
            current = asyncio.current_task()
            if self.owner_task is None:
                self.owner_task = current
            if self._step == 0:
                self._step += 1
                return types.SimpleNamespace(content=[], subtype=None)
            await asyncio.Event().wait()
            raise StopAsyncIteration

        async def aclose(self) -> None:
            self.closed_by = asyncio.current_task()

    def fake_query(*, prompt, options):
        iterator = TaskAwareIterator()
        iterator_holder["iterator"] = iterator
        return iterator

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    stream = _stream_sdk_messages("prompt", object(), "claude")
    first = await anext(stream)
    assert first[0].content == []
    await stream.aclose()

    iterator = iterator_holder["iterator"]
    assert iterator.owner_task is not None
    assert iterator.owner_task is asyncio.current_task()
    assert iterator.closed_by is iterator.owner_task


@pytest.mark.asyncio
async def test_close_internal_query_skips_query_close_from_foreign_task() -> None:
    query_obj = AsyncMock()
    transport = AsyncMock()
    owner_task = asyncio.create_task(asyncio.sleep(0))
    try:
        await _close_internal_query(
            query_obj,
            transport,
            connected=True,
            owner_task=owner_task,
        )
    finally:
        await owner_task

    query_obj.close.assert_not_awaited()
    transport.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_with_tools_uses_plain_string_prompt_even_with_working_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}

    class EmptyIterator:
        def __aiter__(self) -> EmptyIterator:
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    def fake_query(*, prompt, options):
        captured["prompt"] = prompt
        captured["options"] = options
        return EmptyIterator()

    fake_sdk = types.SimpleNamespace(
        query=fake_query,
        ClaudeAgentOptions=lambda **kwargs: types.SimpleNamespace(**kwargs),
    )
    fake_types = types.SimpleNamespace(
        HookContext=object,
        HookInput=object,
        HookJSONOutput=object,
        HookMatcher=lambda **kwargs: types.SimpleNamespace(**kwargs),
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", fake_types)

    from app.adapters.base import Message
    from app.adapters.claude_tools_helpers import complete_with_tools

    async for _ in complete_with_tools(
        messages=[Message(role="user", content="inspect the workspace")],
        model="claude-sonnet-4-6",
        tools=[],
        yolo_mode=True,
        permission_checker=None,
        working_dir=str(tmp_path),
        resume_session_id=None,
        cli_path="/usr/bin/claude",
        model_map={},
        provider_name="claude",
        max_turns=4,
    ):
        pass

    assert isinstance(captured["prompt"], str)
