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
