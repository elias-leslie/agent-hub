"""The streaming done chunk carries the routing evidence SDK callers read."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.sse_writer import SseWriter
from app.api.complete.streaming import _attach_routing, _persist_and_build_done_sse
from app.api.complete.streaming_context import StreamContext


@pytest.mark.asyncio
async def test_done_reports_the_served_model_when_the_primary_served() -> None:
    ctx = StreamContext(
        session_id="s-1", model="claude-opus-5-5", provider="claude", agent_used="neri-reviewer-claude",
        model_used=None, fallback_used=False, user_messages=None, stream_start=0.0,
        is_new_session=False, is_one_shot=False,
    )
    writer = SseWriter(session_id="s-1")
    _attach_routing(writer, ctx)
    usage = SimpleNamespace(input=1, output=1, cache_read=0, cache_write=0)
    message = SimpleNamespace(usage=usage, content=[], stop_reason="stop")

    with (
        patch("app.api.complete.streaming_persistence.save_messages_to_db", AsyncMock()),
        patch("app.api.complete.streaming_persistence._track_citations", AsyncMock()),
        patch("app.api.complete.streaming._log_stream_cost", AsyncMock()),
    ):
        chunk = await _persist_and_build_done_sse(writer=writer, ctx=ctx, message=message, accumulated_content="ok")

    done = json.loads(chunk.removeprefix("data: "))
    assert (done["model_used"], done["agent_used"], done["fallback_used"]) == (
        "claude-opus-5-5", "neri-reviewer-claude", False,
    )


class _FakeDb:
    def __init__(self) -> None:
        self.commit = AsyncMock()

    async def __aenter__(self) -> _FakeDb:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


@pytest.mark.asyncio
async def test_stream_finalize_writes_a_cost_log_row() -> None:
    """Regression: streaming chats wrote no cost_logs rows (0 of 192 sessions)."""
    ctx = StreamContext(
        session_id="s-cost", model="claude-opus-5-5", provider="claude", agent_used="chat",
        model_used=None, fallback_used=False, user_messages=None, stream_start=0.0,
        is_new_session=False, is_one_shot=False,
    )
    writer = SseWriter(session_id="s-cost")
    usage = SimpleNamespace(input=120, output=30, cache_read=7, cache_write=3)
    message = SimpleNamespace(usage=usage, content=[], stop_reason="stop")
    fake_db = _FakeDb()
    log_usage = AsyncMock()

    with (
        patch("app.api.complete.streaming_persistence.save_messages_to_db", AsyncMock()),
        patch("app.api.complete.streaming_persistence._track_citations", AsyncMock()),
        patch("app.db.async_session", lambda: fake_db),
        patch("app.services.context_tracker.log_token_usage", log_usage),
    ):
        await _persist_and_build_done_sse(writer=writer, ctx=ctx, message=message, accumulated_content="ok")

    log_usage.assert_awaited_once()
    args, kwargs = log_usage.await_args_list[0]
    assert args[0] is fake_db
    assert args[1:5] == ("s-cost", "claude-opus-5-5", 120, 30)
    assert (kwargs["cache_read_tokens"], kwargs["cache_write_tokens"]) == (7, 3)
    fake_db.commit.assert_awaited_once()
