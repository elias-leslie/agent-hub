"""The streaming done chunk carries the routing evidence SDK callers read."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.sse_writer import SseWriter
from app.api.complete.streaming import _attach_routing, _persist_and_build_done_sse
from tests.api.stream_test_support import make_stream_ctx, patched_done_persistence


@pytest.mark.asyncio
async def test_done_reports_the_served_model_when_the_primary_served() -> None:
    ctx = make_stream_ctx("s-1", model="claude-opus-5-5", agent_used="neri-reviewer-claude")
    writer = SseWriter(session_id="s-1")
    _attach_routing(writer, ctx)
    usage = SimpleNamespace(input=1, output=1, cache_read=0, cache_write=0)
    message = SimpleNamespace(usage=usage, content=[], stop_reason="stop", model=ctx.model, provider="claude")

    with patched_done_persistence():
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
    ctx = make_stream_ctx("s-cost", model="claude-opus-5-5", agent_used="chat")
    writer = SseWriter(session_id="s-cost")
    usage = SimpleNamespace(input=120, output=30, cache_read=7, cache_write=3)
    message = SimpleNamespace(usage=usage, content=[], stop_reason="stop", model=ctx.model, provider="claude")
    fake_db = _FakeDb()
    log_usage = AsyncMock()

    with (
        patched_done_persistence(log_cost=False),
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
