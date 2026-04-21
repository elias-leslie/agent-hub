from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest

from app.adapters.base import Message
from app.adapters.gemini_events import ToolContentBlock, ToolEvent, ToolMessage
from app.adapters.types import CompletionResult
from app.api.complete.streaming_context import StreamContext
from app.api.complete.streaming_tool_loop import iter_stream_sse_with_tools


@pytest.mark.asyncio
async def test_iter_stream_sse_with_tools_retries_empty_done_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.complete import streaming_tool_loop as mod

    captured_messages: list[list[Message]] = []
    content_buf = [""]

    async def fake_collect_turn_events(
        adapter: object,
        current_messages: list[Message],
        model: str,
        max_tokens: int | None,
        temperature: float,
        stream_kwargs: dict[str, object],
        content_buf_arg: list[str],
        ctx: StreamContext,
    ) -> tuple[list[str], list[object], set[str], str, object | None]:
        captured_messages.append(list(current_messages))
        if len(captured_messages) == 1:
            return [], [], set(), "", SimpleNamespace(
                input_tokens=1,
                output_tokens=1,
                finish_reason="end_turn",
            )
        content_buf_arg[0] = "Final response"
        return [], [], set(), "Final response", SimpleNamespace(
            input_tokens=2,
            output_tokens=3,
            finish_reason="end_turn",
        )

    monkeypatch.setattr(mod, "collect_turn_events", fake_collect_turn_events)
    monkeypatch.setattr(
        "app.services.tools.tool_handler.create_direct_handler",
        lambda **kwargs: AsyncMock(),
    )
    build_done = AsyncMock(return_value="data: done\n\n")
    monkeypatch.setattr(mod, "build_done_sse", build_done)

    ctx = StreamContext(
        session_id="sess-1",
        model="codex/gpt-5.4",
        provider="codex",
        agent_used="memory-curator",
        model_used="codex/gpt-5.4",
        fallback_used=False,
        user_messages=[],
        stream_start=time.monotonic(),
        is_new_session=False,
        is_one_shot=False,
    )

    chunks = []
    async for chunk in iter_stream_sse_with_tools(
        adapter=object(),
        messages=[Message(role="user", content="Curate memory")],
        model="codex/gpt-5.4",
        max_tokens=None,
        temperature=0.2,
        stream_kwargs={},
        content_buf=content_buf,
        ctx=ctx,
        project_id="agent-hub",
        max_tool_turns=3,
    ):
        chunks.append(chunk)

    assert len(captured_messages) == 2
    assert captured_messages[1][-2].role == "assistant"
    assert captured_messages[1][-1].role == "user"
    assert "final user-facing response" in str(captured_messages[1][-1].content).lower()
    build_done.assert_awaited_once()
    assert chunks == ["data: done\n\n"]


@pytest.mark.asyncio
async def test_iter_stream_sse_with_tools_retries_narration_only_done_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.complete import streaming_tool_loop as mod

    captured_messages: list[list[Message]] = []
    content_buf = [""]

    async def fake_collect_turn_events(
        adapter: object,
        current_messages: list[Message],
        model: str,
        max_tokens: int | None,
        temperature: float,
        stream_kwargs: dict[str, object],
        content_buf_arg: list[str],
        ctx: StreamContext,
    ) -> tuple[list[str], list[object], set[str], str, object | None]:
        captured_messages.append(list(current_messages))
        if len(captured_messages) == 1:
            narration = "[[P:started:retrieving current git branch name via git]]"
            content_buf_arg[0] = narration
            return [], [], set(), narration, SimpleNamespace(
                input_tokens=1,
                output_tokens=1,
                finish_reason="end_turn",
            )
        content_buf_arg[0] = "main"
        return [], [], set(), "main", SimpleNamespace(
            input_tokens=2,
            output_tokens=3,
            finish_reason="end_turn",
        )

    monkeypatch.setattr(mod, "collect_turn_events", fake_collect_turn_events)
    monkeypatch.setattr(
        "app.services.tools.tool_handler.create_direct_handler",
        lambda **kwargs: AsyncMock(),
    )
    build_done = AsyncMock(return_value="data: done\n\n")
    monkeypatch.setattr(mod, "build_done_sse", build_done)

    ctx = StreamContext(
        session_id="sess-1",
        model="codex/gpt-5.4",
        provider="codex",
        agent_used="coder",
        model_used="codex/gpt-5.4",
        fallback_used=False,
        user_messages=[],
        stream_start=time.monotonic(),
        is_new_session=False,
        is_one_shot=False,
    )

    chunks = []
    async for chunk in iter_stream_sse_with_tools(
        adapter=object(),
        messages=[Message(role="user", content="What branch am I on?")],
        model="codex/gpt-5.4",
        max_tokens=None,
        temperature=0.2,
        stream_kwargs={},
        content_buf=content_buf,
        ctx=ctx,
        project_id="agent-hub",
        max_tool_turns=3,
    ):
        chunks.append(chunk)

    assert len(captured_messages) == 2
    assert captured_messages[1][-2].role == "assistant"
    assert captured_messages[1][-2].content == "[[P:started:retrieving current git branch name via git]]"
    assert captured_messages[1][-1].role == "user"
    assert "final user-facing response" in str(captured_messages[1][-1].content).lower()
    build_done.assert_awaited_once()
    assert chunks == ["data: done\n\n"]


@pytest.mark.asyncio
async def test_iter_stream_sse_with_tools_prefers_runtime_session_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.complete import streaming_tool_loop as mod

    class FakeRuntimeSession:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

        async def interrupt(self) -> None:
            self.closed = True

        async def respond_to_request(self, **_kwargs) -> None:
            return None

        async def respond_to_user_input(self, **_kwargs) -> None:
            return None

        async def _events(self):
            yield ToolEvent(
                type="assistant",
                message=ToolMessage(
                    content=[
                        ToolContentBlock(type="text", text="Checking state. "),
                        ToolContentBlock(type="tool_use", name="bash", input={"command": "pwd"}, id="tool-1"),
                    ]
                ),
            ), None
            yield ToolEvent(
                type="tool_result",
                content="/srv/workspaces/projects/summitflow",
                tool_use_id="tool-1",
                duration_ms=42,
            ), None
            yield ToolEvent(
                type="result",
                result="Checking state. Active task clear.",
                finish_reason="end_turn",
            ), None

        def events(self):
            return self._events()

    fake_session = FakeRuntimeSession()

    class FakeAdapter:
        async def start_tool_session(self, **_kwargs):
            return fake_session

    build_done = AsyncMock(return_value="data: done\n\n")
    mock_tool_use = AsyncMock()
    mock_tool_result = AsyncMock()
    mock_progress = AsyncMock()
    monkeypatch.setattr(mod, "build_done_sse", build_done)
    monkeypatch.setattr(mod, "mirror_stream_tool_use", mock_tool_use)
    monkeypatch.setattr(mod, "mirror_stream_tool_result", mock_tool_result)
    monkeypatch.setattr(mod, "publish_stream_progress", mock_progress)

    ctx = StreamContext(
        session_id="sess-1",
        model="codex/gpt-5.4",
        provider="codex",
        agent_used="persona",
        model_used="codex/gpt-5.4",
        fallback_used=False,
        user_messages=[],
        stream_start=time.monotonic(),
        is_new_session=False,
        is_one_shot=False,
    )

    content_buf = [""]
    chunks = []
    async for chunk in iter_stream_sse_with_tools(
        adapter=FakeAdapter(),
        messages=[Message(role="user", content="Inspect summitflow")],
        model="codex/gpt-5.4",
        max_tokens=None,
        temperature=0.2,
        stream_kwargs={"tools": [{"name": "bash"}], "working_dir": "/srv/workspaces/projects/summitflow"},
        content_buf=content_buf,
        ctx=ctx,
        project_id="summitflow",
        max_tool_turns=4,
    ):
        chunks.append(chunk)

    assert any('"type":"content"' in chunk for chunk in chunks)
    assert any('"type":"tool_use"' in chunk for chunk in chunks)
    assert any('"type":"tool_result"' in chunk for chunk in chunks)
    assert chunks[-1] == "data: done\n\n"
    assert content_buf[0] == "Checking state. Active task clear."
    assert fake_session.closed is True
    mock_tool_use.assert_awaited_once_with(ANY, "bash", {"command": "pwd"})
    mock_tool_result.assert_awaited_once_with(
        ANY,
        "bash",
        "/srv/workspaces/projects/summitflow",
        duration_ms=42,
        is_error=False,
    )
    mock_progress.assert_awaited()
    build_done.assert_awaited_once()


@pytest.mark.asyncio
async def test_iter_stream_sse_with_tools_runtime_session_falls_back_after_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.complete import streaming_tool_loop as mod

    class FakeRuntimeSession:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

        async def interrupt(self) -> None:
            self.closed = True

        async def respond_to_request(self, **_kwargs) -> None:
            return None

        async def respond_to_user_input(self, **_kwargs) -> None:
            return None

        async def _events(self):
            yield ToolEvent(
                type="assistant",
                message=ToolMessage(
                    content=[
                        ToolContentBlock(
                            type="tool_use",
                            name="read_file",
                            input={"path": "frontend/src/app/persona/page.tsx"},
                            id="tool-1",
                        ),
                    ]
                ),
            ), None
            yield ToolEvent(
                type="tool_result",
                content='(299 lines)      1\t"use client";...',
                tool_use_id="tool-1",
                duration_ms=12,
            ), None
            yield ToolEvent(
                type="result",
                result="",
                finish_reason="end_turn",
            ), None

        def events(self):
            return self._events()

    fake_session = FakeRuntimeSession()

    class FakeAdapter:
        async def start_tool_session(self, **_kwargs):
            return fake_session

    captured_done: dict[str, object] = {}

    async def _fake_build_done_sse(*, event, ctx, accumulated_content, seq):
        captured_done["content"] = accumulated_content
        captured_done["finish_reason"] = getattr(event, "finish_reason", None)
        captured_done["seq"] = seq
        return "data: done\n\n"

    mock_tool_use = AsyncMock()
    mock_tool_result = AsyncMock()
    mock_progress = AsyncMock()
    monkeypatch.setattr(mod, "build_done_sse", _fake_build_done_sse)
    monkeypatch.setattr(mod, "mirror_stream_tool_use", mock_tool_use)
    monkeypatch.setattr(mod, "mirror_stream_tool_result", mock_tool_result)
    monkeypatch.setattr(mod, "publish_stream_progress", mock_progress)

    ctx = StreamContext(
        session_id="sess-1",
        model="codex/gpt-5.4",
        provider="codex",
        agent_used="persona",
        model_used="codex/gpt-5.4",
        fallback_used=False,
        user_messages=[],
        stream_start=time.monotonic(),
        is_new_session=False,
        is_one_shot=False,
    )

    content_buf = [""]
    chunks = []
    async for chunk in iter_stream_sse_with_tools(
        adapter=FakeAdapter(),
        messages=[Message(role="user", content="Review persona operator UI")],
        model="codex/gpt-5.4",
        max_tokens=None,
        temperature=0.2,
        stream_kwargs={"tools": [{"name": "read_file"}], "working_dir": "/srv/workspaces/projects/agent-hub"},
        content_buf=content_buf,
        ctx=ctx,
        project_id="agent-hub",
        max_tool_turns=4,
    ):
        chunks.append(chunk)

    assert any("Tool execution completed, but the agent did not provide a usable final summary." in chunk for chunk in chunks)
    assert chunks[-1] == "data: done\n\n"
    assert "Captured observations:" in content_buf[0]
    assert "read_file: (299 lines)" in content_buf[0]
    assert captured_done["content"] == content_buf[0]
    assert fake_session.closed is True
    mock_tool_use.assert_awaited_once()
    mock_tool_result.assert_awaited_once()
    mock_progress.assert_awaited()


@pytest.mark.asyncio
async def test_iter_stream_sse_with_tools_runtime_session_keeps_streamed_closeout_when_result_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.complete import streaming_tool_loop as mod

    class FakeRuntimeSession:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

        async def interrupt(self) -> None:
            self.closed = True

        async def respond_to_request(self, **_kwargs) -> None:
            return None

        async def respond_to_user_input(self, **_kwargs) -> None:
            return None

        async def _events(self):
            yield ToolEvent(
                type="assistant",
                message=ToolMessage(
                    content=[
                        ToolContentBlock(type="text", text="No code changes needed. "),
                        ToolContentBlock(
                            type="tool_use",
                            name="bash",
                            input={"command": "dt -q -d"},
                            id="tool-1",
                        ),
                    ]
                ),
            ), None
            yield ToolEvent(
                type="tool_result",
                content="CHECK_RESULT:OK",
                tool_use_id="tool-1",
                duration_ms=12,
            ), None
            yield ToolEvent(
                type="assistant",
                message=ToolMessage(
                    content=[
                        ToolContentBlock(type="text", text="Verified current changed set passes.")
                    ]
                ),
            ), None
            yield ToolEvent(
                type="result",
                result="",
                finish_reason="end_turn",
            ), None

        def events(self):
            return self._events()

    fake_session = FakeRuntimeSession()

    class FakeAdapter:
        async def start_tool_session(self, **_kwargs):
            return fake_session

    captured_done: dict[str, object] = {}

    async def _fake_build_done_sse(*, event, ctx, accumulated_content, seq):
        captured_done["content"] = accumulated_content
        captured_done["finish_reason"] = getattr(event, "finish_reason", None)
        captured_done["seq"] = seq
        return "data: done\n\n"

    mock_tool_use = AsyncMock()
    mock_tool_result = AsyncMock()
    mock_progress = AsyncMock()
    monkeypatch.setattr(mod, "build_done_sse", _fake_build_done_sse)
    monkeypatch.setattr(mod, "mirror_stream_tool_use", mock_tool_use)
    monkeypatch.setattr(mod, "mirror_stream_tool_result", mock_tool_result)
    monkeypatch.setattr(mod, "publish_stream_progress", mock_progress)

    ctx = StreamContext(
        session_id="sess-1",
        model="codex/gpt-5.4",
        provider="codex",
        agent_used="persona",
        model_used="codex/gpt-5.4",
        fallback_used=False,
        user_messages=[],
        stream_start=time.monotonic(),
        is_new_session=False,
        is_one_shot=False,
    )

    content_buf = [""]
    chunks = []
    async for chunk in iter_stream_sse_with_tools(
        adapter=FakeAdapter(),
        messages=[Message(role="user", content="Check summitflow state")],
        model="codex/gpt-5.4",
        max_tokens=None,
        temperature=0.2,
        stream_kwargs={"tools": [{"name": "bash"}], "working_dir": "/srv/workspaces/projects/summitflow"},
        content_buf=content_buf,
        ctx=ctx,
        project_id="summitflow",
        max_tool_turns=4,
    ):
        chunks.append(chunk)

    assert all("Tool execution completed, but the agent did not provide a usable final summary." not in chunk for chunk in chunks)
    assert chunks[-1] == "data: done\n\n"
    assert content_buf[0] == "No code changes needed. Verified current changed set passes."
    assert captured_done["content"] == content_buf[0]
    assert fake_session.closed is True
    mock_tool_use.assert_awaited_once()
    mock_tool_result.assert_awaited_once()
    mock_progress.assert_awaited()


@pytest.mark.asyncio
async def test_iter_stream_sse_with_tools_runtime_session_keeps_heartbeat_summary_only_closeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.complete import streaming_tool_loop as mod

    heartbeat_closeout = (
        "HEARTBEAT_ACTION\n"
        "[[S:partial:no changes made; sha task still not closure-ready]]"
    )

    class FakeRuntimeSession:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

        async def interrupt(self) -> None:
            self.closed = True

        async def respond_to_request(self, **_kwargs) -> None:
            return None

        async def respond_to_user_input(self, **_kwargs) -> None:
            return None

        async def _events(self):
            yield ToolEvent(
                type="assistant",
                message=ToolMessage(
                    content=[
                        ToolContentBlock(
                            type="tool_use",
                            name="bash",
                            input={"command": "st pulse"},
                            id="tool-1",
                        ),
                    ]
                ),
            ), None
            yield ToolEvent(
                type="tool_result",
                content="PULSE:sha|cleanup=yes",
                tool_use_id="tool-1",
                duration_ms=12,
            ), None
            yield ToolEvent(
                type="result",
                result=heartbeat_closeout,
                finish_reason="end_turn",
            ), None

        def events(self):
            return self._events()

    fake_session = FakeRuntimeSession()

    class FakeAdapter:
        async def start_tool_session(self, **_kwargs):
            return fake_session

        async def complete(self, **_kwargs):
            return SimpleNamespace(content="unexpected fallback", tool_calls=[], thinking_content=None)

    captured_done: dict[str, object] = {}

    async def _fake_build_done_sse(*, event, ctx, accumulated_content, seq):
        captured_done["content"] = accumulated_content
        captured_done["finish_reason"] = getattr(event, "finish_reason", None)
        captured_done["seq"] = seq
        return "data: done\n\n"

    mock_tool_use = AsyncMock()
    mock_tool_result = AsyncMock()
    mock_progress = AsyncMock()
    monkeypatch.setattr(mod, "build_done_sse", _fake_build_done_sse)
    monkeypatch.setattr(mod, "mirror_stream_tool_use", mock_tool_use)
    monkeypatch.setattr(mod, "mirror_stream_tool_result", mock_tool_result)
    monkeypatch.setattr(mod, "publish_stream_progress", mock_progress)

    ctx = StreamContext(
        session_id="sess-heartbeat-summary-only",
        model="codex/gpt-5.4",
        provider="codex",
        agent_used="persona",
        model_used="codex/gpt-5.4",
        fallback_used=False,
        user_messages=[],
        stream_start=time.monotonic(),
        is_new_session=False,
        is_one_shot=False,
    )

    content_buf = [""]
    chunks = []
    async for chunk in iter_stream_sse_with_tools(
        adapter=FakeAdapter(),
        messages=[Message(role="user", content="Run heartbeat now.")],
        model="codex/gpt-5.4",
        max_tokens=None,
        temperature=0.2,
        stream_kwargs={"tools": [{"name": "bash"}], "working_dir": "/srv/workspaces/projects/agent-hub"},
        content_buf=content_buf,
        ctx=ctx,
        project_id="agent-hub",
        max_tool_turns=4,
    ):
        chunks.append(chunk)

    assert all("Tool execution completed, but the agent did not provide a usable final summary." not in chunk for chunk in chunks)
    assert chunks[-1] == "data: done\n\n"
    assert content_buf[0] == heartbeat_closeout
    assert captured_done["content"] == heartbeat_closeout
    assert fake_session.closed is True
    mock_tool_use.assert_awaited_once()
    mock_tool_result.assert_awaited_once()
    mock_progress.assert_awaited()


@pytest.mark.asyncio
async def test_iter_stream_sse_with_tools_runtime_session_recovers_missing_closeout_from_tool_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.complete import streaming_tool_loop as mod

    class FakeRuntimeSession:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

        async def interrupt(self) -> None:
            self.closed = True

        async def respond_to_request(self, **_kwargs) -> None:
            return None

        async def respond_to_user_input(self, **_kwargs) -> None:
            return None

        async def _events(self):
            yield ToolEvent(
                type="assistant",
                message=ToolMessage(
                    content=[
                        ToolContentBlock(
                            type="tool_use",
                            name="bash",
                            input={"command": "git diff -- backend/app/api/projects/__init__.py"},
                            id="tool-1",
                        ),
                    ]
                ),
            ), None
            yield ToolEvent(
                type="tool_result",
                content="diff --git a/backend/app/api/projects/__init__.py b/backend/app/api/projects/__init__.py",
                tool_use_id="tool-1",
                duration_ms=12,
            ), None

        def events(self):
            return self._events()

    fake_session = FakeRuntimeSession()
    captured_recovery_messages: list[Message] = []
    captured_done: dict[str, object] = {}

    class FakeAdapter:
        async def start_tool_session(self, **_kwargs):
            return fake_session

        async def complete(self, *, messages, model, max_tokens=None, temperature=1.0, **_kwargs):
            captured_recovery_messages[:] = list(messages)
            return CompletionResult(
                content="Blocked: summitflow already has unrelated dirty changes, so no safe ready task is publishable from current repo truth.",
                model=model,
                provider="codex",
                input_tokens=12,
                output_tokens=18,
                finish_reason="end_turn",
            )

    async def _fake_build_done_sse(*, event, ctx, accumulated_content, seq):
        captured_done["content"] = accumulated_content
        captured_done["finish_reason"] = getattr(event, "finish_reason", None)
        captured_done["seq"] = seq
        return "data: done\n\n"

    mock_tool_use = AsyncMock()
    mock_tool_result = AsyncMock()
    mock_progress = AsyncMock()
    monkeypatch.setattr(mod, "build_done_sse", _fake_build_done_sse)
    monkeypatch.setattr(mod, "mirror_stream_tool_use", mock_tool_use)
    monkeypatch.setattr(mod, "mirror_stream_tool_result", mock_tool_result)
    monkeypatch.setattr(mod, "publish_stream_progress", mock_progress)

    ctx = StreamContext(
        session_id="sess-2",
        model="codex/gpt-5.4",
        provider="codex",
        agent_used="persona",
        model_used="codex/gpt-5.4",
        fallback_used=False,
        user_messages=[],
        stream_start=time.monotonic(),
        is_new_session=False,
        is_one_shot=False,
    )

    content_buf = [""]
    chunks = []
    async for chunk in iter_stream_sse_with_tools(
        adapter=FakeAdapter(),
        messages=[Message(role="user", content="Take one summitflow task to completion or report blocker only.")],
        model="codex/gpt-5.4",
        max_tokens=None,
        temperature=0.2,
        stream_kwargs={"tools": [{"name": "bash"}], "working_dir": "/srv/workspaces/projects/summitflow"},
        content_buf=content_buf,
        ctx=ctx,
        project_id="summitflow",
        max_tool_turns=4,
    ):
        chunks.append(chunk)

    assert all("Tool execution completed, but the agent did not provide a usable final summary." not in chunk for chunk in chunks)
    assert chunks[-1] == "data: done\n\n"
    assert "Blocked: summitflow already has unrelated dirty changes" in content_buf[0]
    assert captured_done["content"] == content_buf[0]
    assert captured_recovery_messages[-1].role == "user"
    assert "Captured observations:" in str(captured_recovery_messages[-1].content)
    assert fake_session.closed is True
    mock_tool_use.assert_awaited()
    mock_tool_result.assert_awaited()


@pytest.mark.asyncio
async def test_iter_stream_sse_with_tools_runtime_session_recovers_narration_only_closeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.complete import streaming_tool_loop as mod

    class FakeRuntimeSession:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

        async def interrupt(self) -> None:
            self.closed = True

        async def respond_to_request(self, **_kwargs) -> None:
            return None

        async def respond_to_user_input(self, **_kwargs) -> None:
            return None

        async def _events(self):
            yield ToolEvent(
                type="assistant",
                message=ToolMessage(
                    content=[
                        ToolContentBlock(
                            type="text",
                            text="[[P:started]] Inspect repo state. Pick small ready task.",
                        ),
                        ToolContentBlock(
                            type="tool_use",
                            name="bash",
                            input={"command": "commit.sh --current --skip-checks --msg ... --json"},
                            id="tool-1",
                        ),
                    ]
                ),
            ), None
            yield ToolEvent(
                type="tool_result",
                content='{"status":"SUCCESS","sha":"ddd08c64c"}',
                tool_use_id="tool-1",
                duration_ms=12,
            ), None
            yield ToolEvent(
                type="assistant",
                message=ToolMessage(
                    content=[
                        ToolContentBlock(
                            type="text",
                            text="[[P:decision]] commit.sh allowed with skip-checks only path past unrelated gate break.",
                        ),
                    ]
                ),
            ), None
            yield ToolEvent(
                type="result",
                result="",
                finish_reason="end_turn",
            ), None

        def events(self):
            return self._events()

    fake_session = FakeRuntimeSession()
    captured_done: dict[str, object] = {}

    class FakeAdapter:
        async def start_tool_session(self, **_kwargs):
            return fake_session

        async def complete(self, *, messages, model, max_tokens=None, temperature=1.0, **_kwargs):
            return CompletionResult(
                content="Published summitflow commit ddd08c64c after focused tests passed; full repo type gate still fails from unrelated pre-existing errors.",
                model=model,
                provider="codex",
                input_tokens=12,
                output_tokens=18,
                finish_reason="end_turn",
            )

    async def _fake_build_done_sse(*, event, ctx, accumulated_content, seq):
        captured_done["content"] = accumulated_content
        captured_done["finish_reason"] = getattr(event, "finish_reason", None)
        captured_done["seq"] = seq
        return "data: done\n\n"

    mock_tool_use = AsyncMock()
    mock_tool_result = AsyncMock()
    mock_progress = AsyncMock()
    monkeypatch.setattr(mod, "build_done_sse", _fake_build_done_sse)
    monkeypatch.setattr(mod, "mirror_stream_tool_use", mock_tool_use)
    monkeypatch.setattr(mod, "mirror_stream_tool_result", mock_tool_result)
    monkeypatch.setattr(mod, "publish_stream_progress", mock_progress)

    ctx = StreamContext(
        session_id="sess-3",
        model="codex/gpt-5.4",
        provider="codex",
        agent_used="persona",
        model_used="codex/gpt-5.4",
        fallback_used=False,
        user_messages=[],
        stream_start=time.monotonic(),
        is_new_session=False,
        is_one_shot=False,
    )

    content_buf = [""]
    chunks = []
    async for chunk in iter_stream_sse_with_tools(
        adapter=FakeAdapter(),
        messages=[Message(role="user", content="Take one summitflow task to completion or report blocker only.")],
        model="codex/gpt-5.4",
        max_tokens=None,
        temperature=0.2,
        stream_kwargs={"tools": [{"name": "bash"}], "working_dir": "/srv/workspaces/projects/summitflow"},
        content_buf=content_buf,
        ctx=ctx,
        project_id="summitflow",
        max_tool_turns=4,
    ):
        chunks.append(chunk)

    assert all("Tool execution completed, but the agent did not provide a usable final summary." not in chunk for chunk in chunks)
    assert "Published summitflow commit ddd08c64c" in content_buf[0]
    assert captured_done["content"] == content_buf[0]
    assert fake_session.closed is True
