from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.api.feedback import create_feedback
from app.api.schemas.feedback import FeedbackItemCreate
from app.models.feedback import FeedbackItem


def _feedback_item() -> FeedbackItem:
    item = FeedbackItem(
        component_id="sf.quality",
        feedback_type="friction",
        title="Tool governance: missing quality gate",
        project_id="summitflow",
        status="open",
        vote_count=1,
    )
    object.__setattr__(item, "id", "1640ec32-0000-4000-8000-000000000000")
    object.__setattr__(item, "created_at", datetime.now(UTC))
    object.__setattr__(item, "updated_at", datetime.now(UTC))
    return item


@pytest.mark.asyncio
async def test_create_feedback_vote_if_duplicate_without_session_returns_existing() -> None:
    db = AsyncMock()
    existing = _feedback_item()
    body = FeedbackItemCreate(
        component_id="sf.quality",
        feedback_type="friction",
        title="Tool governance: missing quality gate",
        project_id="summitflow",
        vote_if_duplicate=True,
    )

    with (
        patch(
            "app.api.feedback.feedback_storage.find_duplicate_candidates",
            new=AsyncMock(return_value=[existing]),
        ),
        patch("app.api.feedback.feedback_storage.vote_on_item", new=AsyncMock()) as vote,
        patch("app.api.feedback.feedback_storage.create_feedback_item", new=AsyncMock()) as create,
    ):
        result = await create_feedback(body, db)

    assert result.created is False
    assert result.voted is False
    assert result.item.id == str(existing.id)
    vote.assert_not_awaited()
    create.assert_not_awaited()
    db.commit.assert_not_awaited()
