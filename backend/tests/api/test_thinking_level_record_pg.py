"""A streamed turn records the thinking level it was asked for and the level handed to the provider adapter."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete import stream_completion
from app.api.complete.schemas import MessageInput
from app.llm.types import AssistantMessage, DoneEvent, TextContent, TextDeltaEvent, Usage
from app.models import SessionEvent
from app.services.llm_messages import Message
from tests.api.test_session_stream_pg import test_session_factory  # noqa: F401  (fixture)
from tests.api.test_sessions_listing_pg import add_session, pg_db  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

REASONING_MODEL = "opencode-go/deepseek-v4.1-flash"


def _answer() -> AssistantMessage:
    return AssistantMessage(
        content=[TextContent(text="25")], api="openai-completions", provider="opencode-go", model="deepseek-v4.1-flash",
        usage=Usage(input=5, output=2), stop_reason="stop", timestamp=int(time.time() * 1000),
    )


async def _turn(db: AsyncSession, session_id: str, thinking_level: str | None, model: str = REASONING_MODEL) -> dict[str, Any]:
    await add_session(db, session_id, minutes=1, session_type="chat", status="active")

    async def provider_stream(*_a: object, **_k: object) -> AsyncIterator[Any]:
        yield TextDeltaEvent(content_index=0, delta="25", partial=_answer())
        yield DoneEvent(reason="stop", message=_answer())

    with (
        patch("app.api.complete.streaming.run_completion_stream", new=provider_stream),
        patch("app.api.complete.streaming.route_unavailable_reason", new=AsyncMock(return_value=None)),
        patch("app.api.complete.streaming._record_stream_usage", new=AsyncMock(return_value=0.0)),
        patch("app.api.complete.streaming_persistence._track_citations", new=AsyncMock()),
        patch("app.api.complete.streaming_persistence.mirror_stream_request_metrics", new=AsyncMock()),
    ):
        async for _chunk in stream_completion(
            messages=[Message(role="user", content="How many primes are below 100?")],
            model=model,
            provider="opencode-go",
            temperature=0.7,
            session_id=session_id,
            thinking_level=thinking_level,
            db=db,
            user_messages=[MessageInput(role="user", content="How many primes are below 100?")],
        ):
            pass
    answer = (
        await db.execute(
            select(SessionEvent).where(SessionEvent.session_id == session_id, SessionEvent.role == "assistant")
        )
    ).scalar_one()
    return answer.usage or {}


async def test_a_turn_with_thinking_level_high_records_what_was_asked_and_what_was_sent(
    pg_db: AsyncSession, test_session_factory: None  # noqa: F811
) -> None:
    usage = await _turn(pg_db, "think-high", "high")
    assert usage["thinking"] == {"requested": "high", "sent": "high"}


async def test_a_turn_without_a_level_records_none(pg_db: AsyncSession, test_session_factory: None) -> None:  # noqa: F811
    usage = await _turn(pg_db, "think-none", None)
    assert usage["thinking"] == {"requested": "none", "sent": "none"}


def test_the_sent_level_follows_the_catalog_map_and_is_none_without_reasoning() -> None:
    from dataclasses import replace

    from app.api.complete.orchestrator import sent_thinking_level
    from app.llm.model_resolver import resolve_llm_model

    model = replace(resolve_llm_model(REASONING_MODEL, "opencode-go"), reasoning=True, thinking_level_map={"high": "max"})
    assert sent_thinking_level(model, "high") == "max"
    assert sent_thinking_level(model, "low") == "low"
    assert sent_thinking_level(model, "none") == "none"
    assert sent_thinking_level(replace(model, reasoning=False), "high") == "none"
