"""Unit tests for /api/complete streaming mode.

These tests exercise the wire-format and lifecycle contract of
``stream_completion`` after the Phase 4 cluster B migration, where the
HTTP streaming path drives ``orchestrator.run_completion_stream``
through ``sse_writer``. They do not hit any real service.
"""

from __future__ import annotations

import time
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.base import Message
from app.api.complete import StreamingChunk, stream_completion
from app.api.complete.streaming_context import StreamContext
from app.constants.models import CLAUDE_HAIKU, CLAUDE_SONNET
from app.llm.types import (
    AssistantMessage,
    DoneEvent,
    ErrorEvent,
    StopReason,
    TextDeltaEvent,
    Usage,
)


def _partial_message() -> AssistantMessage:
    return AssistantMessage(
        content=[],
        api="anthropic-messages",
        provider="claude",
        model=CLAUDE_SONNET,
        usage=Usage(),
        stop_reason="stop",
        timestamp=int(time.time() * 1000),
    )


def _done_event(
    *,
    finish_reason: str = "stop",
    input_tokens: int = 5,
    output_tokens: int = 2,
) -> DoneEvent:
    message = AssistantMessage(
        content=[],
        api="anthropic-messages",
        provider="claude",
        model=CLAUDE_SONNET,
        usage=Usage(input=input_tokens, output=output_tokens),
        stop_reason=cast(StopReason, finish_reason),
        timestamp=int(time.time() * 1000),
    )
    return DoneEvent(reason="stop", message=message)


def _error_event(text: str) -> ErrorEvent:
    message = AssistantMessage(
        content=[],
        api="anthropic-messages",
        provider="claude",
        model=CLAUDE_SONNET,
        usage=Usage(),
        stop_reason="error",
        timestamp=int(time.time() * 1000),
        error_message=text,
    )
    return ErrorEvent(reason="error", error=message)


class TestStreamingChunk:
    """Tests for the StreamingChunk Pydantic schema."""

    def test_content_chunk(self) -> None:
        chunk = StreamingChunk(type="content", content="Hello")
        assert chunk.type == "content"
        assert chunk.content == "Hello"

    def test_done_chunk(self) -> None:
        chunk = StreamingChunk(
            type="done",
            model=CLAUDE_SONNET,
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
            session_id="test-session",
        )
        assert chunk.type == "done"
        assert chunk.model == CLAUDE_SONNET
        assert chunk.input_tokens == 10

    def test_error_chunk(self) -> None:
        chunk = StreamingChunk(type="error", error="Something went wrong")
        assert chunk.type == "error"
        assert chunk.error == "Something went wrong"

    def test_agent_routing_fields(self) -> None:
        chunk = StreamingChunk(
            type="done",
            agent_used="coder",
            model_used=CLAUDE_HAIKU,
            fallback_used=True,
        )
        assert chunk.agent_used == "coder"
        assert chunk.model_used == "claude-haiku-4-5"
        assert chunk.fallback_used is True


def _patch_persistence():
    """Patch the DB-side persistence helpers stream_completion calls on done."""
    return (
        patch(
            "app.api.complete.streaming_persistence.save_messages_to_db",
            new=AsyncMock(),
        ),
        patch(
            "app.api.complete.streaming_persistence._track_citations",
            new=AsyncMock(),
        ),
        patch(
            "app.api.complete.streaming_persistence.close_one_shot_session",
            new=AsyncMock(),
        ),
    )


class TestStreamCompletionGenerator:
    """Tests for stream_completion's wire-format contract."""

    @pytest.mark.asyncio
    async def test_yields_sse_format(self) -> None:
        async def mock_stream(*_args: object, **_kwargs: object):
            yield TextDeltaEvent(content_index=0, delta="Hello", partial=_partial_message())
            yield _done_event()

        save, citations, close = _patch_persistence()
        with (
            save, citations, close,
            patch("app.api.complete.streaming.run_completion_stream", new=mock_stream),
        ):
            chunks = []
            async for chunk in stream_completion(
                messages=[Message(role="user", content="Hi")],
                model=CLAUDE_SONNET,
                provider="claude",
                temperature=0.7,
                session_id="test-session",
            ):
                chunks.append(chunk)

        for chunk in chunks:
            assert chunk.startswith("data: "), f"Not SSE format: {chunk}"
        assert chunks[-1] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_content_events(self) -> None:
        async def mock_stream(*_args: object, **_kwargs: object):
            yield TextDeltaEvent(content_index=0, delta="Hello", partial=_partial_message())
            yield TextDeltaEvent(content_index=0, delta=" world", partial=_partial_message())
            yield _done_event(input_tokens=5, output_tokens=3)

        save, citations, close = _patch_persistence()
        with (
            save, citations, close,
            patch("app.api.complete.streaming.run_completion_stream", new=mock_stream),
        ):
            chunks = []
            async for chunk in stream_completion(
                messages=[Message(role="user", content="Hi")],
                model=CLAUDE_SONNET,
                provider="claude",
                temperature=0.7,
                session_id="test-session",
            ):
                chunks.append(chunk)

        content_chunks = [c for c in chunks if '"type": "content"' in c]
        assert len(content_chunks) == 2

    @pytest.mark.asyncio
    async def test_stream_completion_unregisters_context_when_finished(self) -> None:
        async def mock_stream(*_args: object, **_kwargs: object):
            yield _done_event()

        save, citations, close = _patch_persistence()
        with (
            save, citations, close,
            patch("app.api.complete.streaming.run_completion_stream", new=mock_stream),
        ):
            async for _chunk in stream_completion(
                messages=[Message(role="user", content="Hi")],
                model=CLAUDE_SONNET,
                provider="claude",
                temperature=0.7,
                session_id="cleanup-session",
            ):
                pass

        # After the stream finishes, the cancel registry should not know this session.
        assert StreamContext.cancel("cleanup-session") is False

    @pytest.mark.asyncio
    async def test_done_event_includes_metadata(self) -> None:
        import json

        async def mock_stream(*_args: object, **_kwargs: object):
            yield _done_event(finish_reason="stop", input_tokens=10, output_tokens=5)

        save, citations, close = _patch_persistence()
        with (
            save, citations, close,
            patch("app.api.complete.streaming.run_completion_stream", new=mock_stream),
        ):
            chunks = []
            async for chunk in stream_completion(
                messages=[Message(role="user", content="Hi")],
                model=CLAUDE_SONNET,
                provider="claude",
                temperature=0.7,
                session_id="test-session",
                agent_used="coder",
                model_used=CLAUDE_SONNET,
                fallback_used=False,
            ):
                chunks.append(chunk)

        done_chunk = None
        for c in chunks:
            if '"type": "done"' in c:
                done_chunk = json.loads(c.replace("data: ", "").strip())
                break

        assert done_chunk is not None
        assert done_chunk["model"] == CLAUDE_SONNET
        assert done_chunk["provider"] == "claude"
        assert done_chunk["session_id"] == "test-session"
        assert done_chunk["agent_used"] == "coder"
        assert done_chunk["input_tokens"] == 10
        assert done_chunk["output_tokens"] == 5
        assert done_chunk["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_error_handling(self) -> None:
        async def mock_stream(*_args: object, **_kwargs: object):
            yield _error_event("API error occurred")

        save, citations, close = _patch_persistence()
        with (
            save, citations, close,
            patch("app.api.complete.streaming.run_completion_stream", new=mock_stream),
        ):
            chunks = []
            async for chunk in stream_completion(
                messages=[Message(role="user", content="Hi")],
                model=CLAUDE_SONNET,
                provider="claude",
                temperature=0.7,
                session_id="test-session",
            ):
                chunks.append(chunk)

        error_chunks = [c for c in chunks if '"type": "error"' in c]
        assert len(error_chunks) == 1
        assert "API error occurred" in error_chunks[0]

    @pytest.mark.asyncio
    async def test_connected_event_includes_model_and_provider(self) -> None:
        import json

        async def mock_stream(*_args: object, **_kwargs: object):
            yield _done_event()

        save, citations, close = _patch_persistence()
        with (
            save, citations, close,
            patch("app.api.complete.streaming.run_completion_stream", new=mock_stream),
        ):
            chunks = []
            async for chunk in stream_completion(
                messages=[Message(role="user", content="Hi")],
                model=CLAUDE_SONNET,
                provider="claude",
                temperature=0.7,
                session_id="connected-session",
            ):
                chunks.append(chunk)

        first = json.loads(chunks[0].replace("data: ", "").strip())
        assert first["type"] == "connected"
        assert first["session_id"] == "connected-session"
        assert first["model"] == CLAUDE_SONNET
        assert first["provider"] == "claude"
