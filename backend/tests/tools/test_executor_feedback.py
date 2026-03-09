"""Tests for _executor_feedback — manage_feedback governance actions."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools._executor_feedback import manage_feedback


def _make_item(
    id: str = "12345678-1234-1234-1234-123456789abc",
    feedback_type: str = "friction",
    component_id: str = "sf.cli",
    title: str = "CLI is slow",
    vote_count: int = 3,
) -> MagicMock:
    item = MagicMock()
    item.id = id
    item.feedback_type = feedback_type
    item.component_id = component_id
    item.title = title
    item.vote_count = vote_count
    return item


def _mock_async_session():
    """Create a mock async_session context manager."""
    mock_db = AsyncMock()

    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session, mock_db


class TestManageFeedbackSearch:
    @pytest.mark.anyio
    async def test_search_returns_table(self) -> None:
        item = _make_item()
        session_factory, _mock_db = _mock_async_session()

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.services.feedback_storage.search_feedback_items",
                new_callable=AsyncMock,
                return_value=[item],
            ) as mock_search,
        ):
            result = await manage_feedback(action="search")

        assert "12345678" in result
        assert "friction" in result
        assert "sf.cli" in result
        assert "CLI is slow" in result
        mock_search.assert_called_once()

    @pytest.mark.anyio
    async def test_search_empty(self) -> None:
        session_factory, _mock_db = _mock_async_session()

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.services.feedback_storage.search_feedback_items",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await manage_feedback(action="search")

        assert "No open feedback" in result


class TestManageFeedbackList:
    @pytest.mark.anyio
    async def test_list_returns_table(self) -> None:
        item = _make_item()
        item.status = "acknowledged"
        session_factory, _mock_db = _mock_async_session()

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.services.feedback_storage.search_feedback_items",
                new_callable=AsyncMock,
                return_value=[item],
            ) as mock_search,
        ):
            result = await manage_feedback(action="list", status="acknowledged", sort="newest")

        assert "Feedback items" in result
        assert "acknowledged" in result
        mock_search.assert_called_once()

    @pytest.mark.anyio
    async def test_list_empty(self) -> None:
        session_factory, _mock_db = _mock_async_session()

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.services.feedback_storage.search_feedback_items",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await manage_feedback(action="list")

        assert "No feedback items" in result


class TestManageFeedbackGet:
    @pytest.mark.anyio
    async def test_get_returns_details(self) -> None:
        item = _make_item()
        item.status = "open"
        item.project_id = "agent-hub"
        item.severity = "medium"
        item.created_at = MagicMock(isoformat=MagicMock(return_value="2026-03-09T12:00:00+00:00"))
        item.description = "Detailed description"
        item.resolution_note = None
        item.linked_task_id = "task-123"
        vote = MagicMock(session_id="sess-1", agent_slug="persona", comment="seen this too")
        session_factory, _mock_db = _mock_async_session()

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.services.feedback_storage.resolve_feedback_id",
                new_callable=AsyncMock,
                return_value=str(item.id),
            ),
            patch(
                "app.services.feedback_storage.get_feedback_item",
                new_callable=AsyncMock,
                return_value=item,
            ),
            patch(
                "app.services.feedback_storage.get_feedback_votes",
                new_callable=AsyncMock,
                return_value=[vote],
            ),
        ):
            result = await manage_feedback(action="get", item_id="12345678")

        assert "Detailed description" in result
        assert "Linked task: task-123" in result
        assert "sess-1 by persona" in result

    @pytest.mark.anyio
    async def test_get_requires_id(self) -> None:
        result = await manage_feedback(action="get")
        assert "item_id is required" in result


class TestManageFeedbackSummary:
    @pytest.mark.anyio
    async def test_summary_returns_clusters(self) -> None:
        session_factory, _mock_db = _mock_async_session()
        summary = {
            "total_items": 6,
            "counts_by_type_status": [
                {"feedback_type": "friction", "status": "open", "count": 2},
                {"feedback_type": "idea", "status": "acknowledged", "count": 1},
                {"feedback_type": "praise", "status": "resolved", "count": 3},
            ],
            "by_component": [
                {
                    "component_id": "sf.cli",
                    "open_count": 2,
                    "resolved_count": 1,
                    "total_votes": 4,
                }
            ],
            "top_unresolved": [
                {
                    "id": "12345678-1234-1234-1234-123456789abc",
                    "feedback_type": "friction",
                    "component_id": "sf.cli",
                    "vote_count": 4,
                    "title": "CLI output is noisy",
                }
            ],
        }

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.services.feedback_storage.get_feedback_summary",
                new_callable=AsyncMock,
                return_value=summary,
            ),
        ):
            result = await manage_feedback(action="summary", days=14)

        assert "Feedback summary (14d)" in result
        assert "unresolved=3" in result
        assert "sf.cli: open=2" in result
        assert "CLI output is noisy" in result


class TestManageFeedbackResolve:
    @pytest.mark.anyio
    async def test_resolve_success(self) -> None:
        item = _make_item()
        session_factory, _mock_db = _mock_async_session()

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.services.feedback_storage.resolve_feedback_id",
                new_callable=AsyncMock,
                return_value=str(item.id),
            ),
            patch(
                "app.services.feedback_storage.update_feedback_status",
                new_callable=AsyncMock,
                return_value=item,
            ) as mock_update,
        ):
            result = await manage_feedback(action="resolve", item_id="12345678")

        assert "Resolved" in result
        assert "12345678" in result
        mock_update.assert_called_once()

    @pytest.mark.anyio
    async def test_resolve_not_found(self) -> None:
        session_factory, _mock_db = _mock_async_session()

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.services.feedback_storage.resolve_feedback_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await manage_feedback(action="resolve", item_id="deadbeef")

        assert "No feedback item found" in result

    @pytest.mark.anyio
    async def test_resolve_missing_id(self) -> None:
        result = await manage_feedback(action="resolve")
        assert "item_id is required" in result


class TestManageFeedbackVote:
    @pytest.mark.anyio
    async def test_vote_success(self) -> None:
        session_factory, _mock_db = _mock_async_session()
        mock_vote = MagicMock()

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.services.feedback_storage.resolve_feedback_id",
                new_callable=AsyncMock,
                return_value="12345678-1234-1234-1234-123456789abc",
            ),
            patch(
                "app.services.feedback_storage.vote_on_item",
                new_callable=AsyncMock,
                return_value=mock_vote,
            ) as mock_vote_fn,
        ):
            result = await manage_feedback(action="vote", item_id="12345678", comment="me too")

        assert "Voted on" in result
        mock_vote_fn.assert_called_once()

    @pytest.mark.anyio
    async def test_vote_already_voted(self) -> None:
        session_factory, _mock_db = _mock_async_session()

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.services.feedback_storage.resolve_feedback_id",
                new_callable=AsyncMock,
                return_value="12345678-1234-1234-1234-123456789abc",
            ),
            patch(
                "app.services.feedback_storage.vote_on_item",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await manage_feedback(action="vote", item_id="12345678")

        assert "Already voted" in result

    @pytest.mark.anyio
    async def test_vote_missing_id(self) -> None:
        result = await manage_feedback(action="vote")
        assert "item_id is required" in result


class TestManageFeedbackUnknownAction:
    @pytest.mark.anyio
    async def test_unknown_action(self) -> None:
        result = await manage_feedback(action="archive")
        assert "Unknown action" in result
        assert "search/list/get/summary/resolve/vote/delete" in result


class TestManageFeedbackDelete:
    @pytest.mark.anyio
    async def test_delete_success(self) -> None:
        item = _make_item()
        session_factory, _mock_db = _mock_async_session()

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.services.feedback_storage.resolve_feedback_id",
                new_callable=AsyncMock,
                return_value=str(item.id),
            ),
            patch(
                "app.services.feedback_storage.get_feedback_item",
                new_callable=AsyncMock,
                return_value=item,
            ),
            patch(
                "app.services.feedback_storage.delete_feedback_item",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await manage_feedback(action="delete", item_id="12345678")

        assert "Deleted" in result
        assert "12345678" in result

    @pytest.mark.anyio
    async def test_delete_requires_id(self) -> None:
        result = await manage_feedback(action="delete", item_id=None)
        assert "item_id is required" in result
