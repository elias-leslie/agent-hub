from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.streaming_persistence import _track_citations


@pytest.mark.asyncio
async def test_track_citations_reuses_shared_inline_tag_tracker() -> None:
    db = AsyncMock()

    @asynccontextmanager
    async def fake_async_session():
        yield db

    with (
        patch("app.db.async_session", fake_async_session),
        patch(
            "app.api.complete.citation_tracker._track_inline_tags",
            new_callable=AsyncMock,
        ) as mock_track_inline_tags,
        patch(
            "app.services.memory.citation_parser.extract_uuid_prefixes",
            return_value=[],
        ),
    ):
        await _track_citations(
            session_id="session-123",
            accumulated_content="Done. [[S:completed:Finished the requested change.]]",
            agent_id="coder",
            model_used="codex/gpt-5.4",
        )

    mock_track_inline_tags.assert_awaited_once_with(
        "Done. [[S:completed:Finished the requested change.]]",
        db,
        "session-123",
        "coder",
        "codex/gpt-5.4",
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_done_chunk_reports_the_served_model_when_the_primary_served() -> None:
    """SDK callers read routing evidence from done; model_used must not be empty."""
    import json
    from types import SimpleNamespace

    from app.api.complete.streaming_context import StreamContext
    from app.api.complete.streaming_persistence import build_done_sse

    ctx = StreamContext(
        session_id="s-1", model="claude-opus-5-5", provider="claude", agent_used="neri-reviewer-claude",
        model_used=None, fallback_used=False, user_messages=None, stream_start=0.0,
        is_new_session=True, is_one_shot=True,
    )
    with patch("app.api.complete.streaming_persistence._persist_completion", AsyncMock(return_value=0.0)):
        chunk = await build_done_sse(SimpleNamespace(input_tokens=1, output_tokens=1), ctx, "ok", 3)

    done = json.loads(chunk.removeprefix("data: "))
    assert (done["model_used"], done["agent_used"], done["fallback_used"]) == (
        "claude-opus-5-5", "neri-reviewer-claude", False,
    )
