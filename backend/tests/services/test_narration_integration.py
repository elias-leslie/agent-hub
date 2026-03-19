"""Integration test for narration pipeline: extraction → storage → API."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import SessionEventType
from app.models.narration_tag import NarrationTag as NarrationTagModel
from app.services.narration_extraction import extract_narration_from_event
from app.storage.narration_tags import get_narration_tags_for_task

TASK_ID = "test-task-narration"
SESSION_ID = "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"

CONTENT_WITH_TAGS = (
    "Working on the feature. "
    "[[P:started:Implementing feature]] "
    "Made changes to [[P:modified:api/endpoint.py]] "
    "Looking good."
)


def _make_tag_model(tag_type: str, content: str, tag_id: int) -> NarrationTagModel:
    """Create a NarrationTagModel instance for mock returns."""
    tag = NarrationTagModel(
        task_id=TASK_ID,
        session_id=SESSION_ID,
        tag_type=tag_type,
        content=content,
    )
    tag.id = tag_id
    tag.created_at = datetime.now(UTC)
    return tag


class TestNarrationPipelineIntegration:
    """Test extraction → storage → API narration flow."""

    @pytest.mark.anyio
    async def test_extract_stores_tags_for_linked_session(self) -> None:
        """extract_narration_from_event persists parsed tags when session has external_id."""
        db = AsyncMock()
        # Mock session lookup to return TASK_ID as external_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = TASK_ID
        db.execute.return_value = mock_result

        count = await extract_narration_from_event(
            db,
            session_id=SESSION_ID,
            event_type=SessionEventType.ASSISTANT_MESSAGE,
            content=CONTENT_WITH_TAGS,
        )

        assert count == 2
        # Verify bulk insert was called via db.add_all + flush
        assert db.add_all.called
        tags_added = db.add_all.call_args[0][0]
        assert len(tags_added) == 2
        assert tags_added[0].tag_type == "started"
        assert tags_added[0].content == "Implementing feature"
        assert tags_added[1].tag_type == "modified"
        assert tags_added[1].content == "api/endpoint.py"
        assert all(t.task_id == TASK_ID for t in tags_added)
        assert all(t.session_id == SESSION_ID for t in tags_added)

    @pytest.mark.anyio
    async def test_extract_skips_non_assistant_event(self) -> None:
        """Non-assistant events produce zero tags."""
        db = AsyncMock()
        count = await extract_narration_from_event(
            db,
            session_id=SESSION_ID,
            event_type=SessionEventType.USER_MESSAGE,
            content=CONTENT_WITH_TAGS,
        )
        assert count == 0
        db.execute.assert_not_called()

    @pytest.mark.anyio
    async def test_extract_skips_no_external_id(self) -> None:
        """Sessions without external_id (no linked task) skip storage."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        count = await extract_narration_from_event(
            db,
            session_id=SESSION_ID,
            event_type=SessionEventType.ASSISTANT_MESSAGE,
            content=CONTENT_WITH_TAGS,
        )
        assert count == 0

    @pytest.mark.anyio
    async def test_extract_with_preloaded_session(self) -> None:
        """When session object is passed, skips DB lookup."""
        db = AsyncMock()
        session = MagicMock()
        session.external_id = TASK_ID

        count = await extract_narration_from_event(
            db,
            session_id=SESSION_ID,
            event_type=SessionEventType.ASSISTANT_MESSAGE,
            content=CONTENT_WITH_TAGS,
            session=session,
        )
        assert count == 2
        # Should NOT have queried for session — it was provided
        # Only call should be flush from insert_narration_tags_bulk
        assert not any(
            "Session" in str(call) for call in db.execute.call_args_list
        )

    @pytest.mark.anyio
    async def test_get_narration_tags_returns_stored_tags(self) -> None:
        """get_narration_tags_for_task returns tags ordered by creation."""
        db = AsyncMock()
        expected_tags = [
            _make_tag_model("started", "Implementing feature", 1),
            _make_tag_model("modified", "api/endpoint.py", 2),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = expected_tags
        db.execute.return_value = mock_result

        tags = await get_narration_tags_for_task(db, TASK_ID)

        assert len(tags) == 2
        assert tags[0].tag_type == "started"
        assert tags[1].tag_type == "modified"

    def test_api_returns_narration_timeline(self, api_client, mock_db_session) -> None:  # type: ignore[no-untyped-def]
        """GET /api/narration/tasks/{task_id} returns structured timeline."""
        expected_tags = [
            _make_tag_model("started", "Implementing feature", 1),
            _make_tag_model("modified", "api/endpoint.py", 2),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = expected_tags
        mock_db_session.execute.return_value = mock_result

        response = api_client.get(f"/api/narration/tasks/{TASK_ID}")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == TASK_ID
        assert data["total"] == 2
        assert len(data["tags"]) == 2
        assert data["tags"][0]["tag_type"] == "started"
        assert data["tags"][0]["content"] == "Implementing feature"
        assert data["tags"][1]["tag_type"] == "modified"
        assert data["tags"][1]["content"] == "api/endpoint.py"

    def test_api_empty_task_returns_zero_tags(self, api_client, mock_db_session) -> None:  # type: ignore[no-untyped-def]
        """GET /api/narration/tasks/{task_id} returns empty list for unknown task."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        response = api_client.get("/api/narration/tasks/nonexistent-task")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["tags"] == []
