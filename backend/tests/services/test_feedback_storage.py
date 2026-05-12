"""Tests for feedback storage CRUD operations."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.feedback import FeedbackItem, FeedbackVote
from app.services.feedback_storage import (
    archive_stale_feedback_items,
    count_feedback_items,
    create_feedback_item,
    find_duplicate_candidates,
    get_component_feedback,
    get_feedback_item,
    get_feedback_summary,
    get_feedback_votes,
    merge_feedback_items,
    purge_old_archived_feedback_items,
    search_feedback_items,
    update_feedback_status,
    vote_on_item,
)


def make_feedback_item(
    *,
    id: str = "item-1",
    component_id: str = "sf.cli",
    feedback_type: str = "friction",
    title: str = "Test feedback",
    description: str | None = None,
    severity: str | None = None,
    status: str = "open",
    project_id: str = "summitflow",
    vote_count: int = 1,
) -> FeedbackItem:
    """Create a test FeedbackItem without hitting DB."""
    item = FeedbackItem(
        component_id=component_id,
        feedback_type=feedback_type,
        title=title,
        description=description,
        severity=severity,
        status=status,
        project_id=project_id,
        vote_count=vote_count,
    )
    # Manually set fields that would be set by DB
    object.__setattr__(item, "id", id)
    object.__setattr__(item, "created_at", datetime.now(UTC))
    object.__setattr__(item, "updated_at", datetime.now(UTC))
    return item


def make_feedback_vote(
    *,
    id: str = "vote-1",
    feedback_item_id: str = "item-1",
    session_id: str = "sess-1",
    comment: str | None = None,
) -> FeedbackVote:
    """Create a test FeedbackVote."""
    vote = FeedbackVote(
        feedback_item_id=feedback_item_id,
        session_id=session_id,
        comment=comment,
    )
    object.__setattr__(vote, "id", id)
    object.__setattr__(vote, "created_at", datetime.now(UTC))
    return vote


class TestCreateFeedbackItem:
    """Tests for create_feedback_item."""

    @pytest.mark.asyncio
    async def test_creates_item_with_required_fields(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        item = await create_feedback_item(
            db,
            component_id="sf.cli",
            feedback_type="friction",
            title="Error on claim",
            project_id="summitflow",
        )

        assert item.component_id == "sf.cli"
        assert item.feedback_type == "friction"
        assert item.title == "Error on claim"
        assert item.project_id == "summitflow"
        db.add.assert_called_once_with(item)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_item_with_all_optional_fields(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        item = await create_feedback_item(
            db,
            component_id="ah.memory",
            feedback_type="idea",
            title="Cross-project preload",
            project_id="agent-hub",
            description="Pre-load context for multi-repo sessions",
            severity=None,
            session_id="sess-123",
            agent_slug="coder",
            model_used="claude-sonnet-4-20250514",
            session_type="claude_code",
        )

        assert item.description == "Pre-load context for multi-repo sessions"
        assert item.created_by_session_id == "sess-123"
        assert item.agent_slug == "coder"
        assert item.model_used == "claude-sonnet-4-20250514"
        assert item.session_type == "claude_code"

    @pytest.mark.asyncio
    async def test_friction_includes_severity(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        item = await create_feedback_item(
            db,
            component_id="sf.dt",
            feedback_type="friction",
            title="dt --quick times out",
            project_id="summitflow",
            severity="high",
        )

        assert item.severity == "high"


class TestSearchFeedbackItems:
    """Tests for search_feedback_items."""

    @pytest.mark.asyncio
    async def test_returns_list_of_items(self) -> None:
        db = AsyncMock()
        items = [make_feedback_item(id="a"), make_feedback_item(id="b")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = items
        db.execute.return_value = mock_result

        result = await search_feedback_items(db)

        assert len(result) == 2
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_result(self) -> None:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        result = await search_feedback_items(db, component_id="sf.cli")

        assert result == []


    @pytest.mark.asyncio
    async def test_active_status_uses_active_status_filter(self) -> None:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        await search_feedback_items(db, status="active")

        stmt = db.execute.await_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "IN ('open', 'acknowledged')" in compiled

    @pytest.mark.asyncio
    async def test_unknown_sort_defaults_to_vote_ordering(self) -> None:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        await search_feedback_items(db, sort="custom")

        stmt = db.execute.await_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY feedback_items.vote_count DESC" in compiled


class TestCountFeedbackItems:
    """Tests for count_feedback_items."""

    @pytest.mark.asyncio
    async def test_active_status_uses_active_status_filter(self) -> None:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 2
        db.execute.return_value = mock_result

        total = await count_feedback_items(db, status="active")

        assert total == 2
        stmt = db.execute.await_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "IN ('open', 'acknowledged')" in compiled


class TestFindDuplicateCandidates:
    """Tests for find_duplicate_candidates."""

    @pytest.mark.asyncio
    async def test_searches_same_component_globally_with_project_preference(self) -> None:
        db = AsyncMock()
        first = make_feedback_item(id="first", project_id="summitflow")
        second = make_feedback_item(id="second", project_id="agent-hub")

        rows_result = MagicMock()
        rows_result.mappings.return_value.all.return_value = [
            {"id": "first"},
            {"id": "second"},
        ]
        orm_result = MagicMock()
        orm_result.scalars.return_value.all.return_value = [second, first]
        db.execute.side_effect = [rows_result, orm_result]

        result = await find_duplicate_candidates(
            db,
            component_id="sf.cli",
            feedback_type="friction",
            project_id="agent-hub",
            title="st feedback report --vote-if-match created duplicates",
        )

        stmt, params = db.execute.await_args_list[0].args
        sql = str(stmt)
        assert "AND fi.project_id = :project_id" not in sql
        assert "lower(fi.title) = lower(:title)" in sql
        assert "ORDER BY (fi.project_id = :project_id) DESC" in sql
        assert "(lower(fi.title) = lower(:title)) DESC" in sql
        assert "rank DESC" in sql
        assert params["project_id"] == "agent-hub"
        assert result == [first, second]


class TestGetFeedbackItem:
    """Tests for get_feedback_item."""

    @pytest.mark.asyncio
    async def test_returns_item_when_found(self) -> None:
        db = AsyncMock()
        item = make_feedback_item()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = item
        db.execute.return_value = mock_result

        result = await get_feedback_item(db, "item-1")

        assert result is item

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        result = await get_feedback_item(db, "nonexistent")

        assert result is None


class TestGetFeedbackVotes:
    """Tests for get_feedback_votes."""

    @pytest.mark.asyncio
    async def test_returns_votes_for_item(self) -> None:
        db = AsyncMock()
        votes = [make_feedback_vote(id="v1"), make_feedback_vote(id="v2")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = votes
        db.execute.return_value = mock_result

        result = await get_feedback_votes(db, "item-1")

        assert len(result) == 2


class TestVoteOnItem:
    """Tests for vote_on_item."""

    @pytest.mark.asyncio
    async def test_creates_vote_and_increments_count(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        # First execute: check existing vote (none found)
        check_result = MagicMock()
        check_result.scalar_one_or_none.return_value = None
        # Second execute: update vote_count
        update_result = MagicMock()
        db.execute.side_effect = [check_result, update_result]

        vote = await vote_on_item(
            db,
            item_id="item-1",
            session_id="sess-1",
            comment="Hit this too",
            agent_slug="coder",
        )

        assert vote is not None
        assert vote.feedback_item_id == "item-1"
        assert vote.session_id == "sess-1"
        assert vote.comment == "Hit this too"
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_for_duplicate_vote(self) -> None:
        db = AsyncMock()
        # Existing vote found
        check_result = MagicMock()
        check_result.scalar_one_or_none.return_value = make_feedback_vote()
        db.execute.return_value = check_result

        vote = await vote_on_item(
            db,
            item_id="item-1",
            session_id="sess-1",
        )

        assert vote is None
        db.add.assert_not_called()


class TestUpdateFeedbackStatus:
    """Tests for update_feedback_status."""

    @pytest.mark.asyncio
    async def test_updates_status(self) -> None:
        db = AsyncMock()
        db.flush = AsyncMock()
        item = make_feedback_item(status="open")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = item
        db.execute.return_value = mock_result

        result = await update_feedback_status(db, "item-1", status="acknowledged")

        assert result is not None
        assert result.status == "acknowledged"

    @pytest.mark.asyncio
    async def test_resolve_sets_resolved_at(self) -> None:
        db = AsyncMock()
        db.flush = AsyncMock()
        item = make_feedback_item(status="open")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = item
        db.execute.return_value = mock_result

        result = await update_feedback_status(
            db,
            "item-1",
            status="resolved",
            resolution_note="Fixed in commit abc123",
        )

        assert result is not None
        assert result.status == "resolved"
        assert result.resolution_note == "Fixed in commit abc123"

    @pytest.mark.asyncio
    async def test_link_task(self) -> None:
        db = AsyncMock()
        db.flush = AsyncMock()
        item = make_feedback_item()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = item
        db.execute.return_value = mock_result

        result = await update_feedback_status(
            db, "item-1", linked_task_id="task-abc"
        )

        assert result is not None
        assert result.linked_task_id == "task-abc"

    @pytest.mark.asyncio
    async def test_reopen_clears_resolved_at(self) -> None:
        db = AsyncMock()
        db.flush = AsyncMock()
        item = make_feedback_item(status="resolved")
        object.__setattr__(item, "resolved_at", datetime.now(UTC))
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = item
        db.execute.return_value = mock_result

        result = await update_feedback_status(db, "item-1", status="open")

        assert result is not None
        assert result.status == "open"
        assert result.resolved_at is None

    @pytest.mark.asyncio
    async def test_returns_none_when_item_not_found(self) -> None:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        result = await update_feedback_status(db, "nonexistent", status="resolved")

        assert result is None


class TestGetFeedbackSummary:
    """Tests for get_feedback_summary."""

    @pytest.mark.asyncio
    async def test_returns_summary_structure(self) -> None:
        db = AsyncMock()

        # Mock three db.execute calls: counts, top items, by component
        counts_result = MagicMock()
        counts_result.mappings.return_value.all.return_value = [
            {"feedback_type": "friction", "status": "open", "count": 5},
            {"feedback_type": "idea", "status": "open", "count": 3},
        ]

        top_result = MagicMock()
        top_result.mappings.return_value.all.return_value = [
            {
                "id": "item-1",
                "component_id": "sf.cli",
                "feedback_type": "friction",
                "title": "Error on claim",
                "vote_count": 5,
                "status": "open",
                "created_at": datetime.now(UTC),
            }
        ]

        component_result = MagicMock()
        component_result.mappings.return_value.all.return_value = [
            {
                "component_id": "sf.cli",
                "open_count": 3,
                "resolved_count": 1,
                "wont_fix_count": 0,
                "archived_count": 0,
                "friction_count": 2,
                "idea_count": 1,
                "praise_count": 0,
                "total_votes": 10,
            }
        ]

        db.execute.side_effect = [counts_result, top_result, component_result]

        summary = await get_feedback_summary(db)

        assert summary["total_items"] == 8
        assert len(summary["counts_by_type_status"]) == 2
        assert len(summary["top_unresolved"]) == 1
        assert len(summary["by_component"]) == 1

    @pytest.mark.asyncio
    async def test_empty_summary(self) -> None:
        db = AsyncMock()

        empty_result = MagicMock()
        empty_result.mappings.return_value.all.return_value = []

        db.execute.side_effect = [empty_result, empty_result, empty_result]

        summary = await get_feedback_summary(db)

        assert summary["total_items"] == 0
        assert summary["top_unresolved"] == []
        assert summary["by_component"] == []


class TestMergeFeedbackItems:
    """Tests for merge_feedback_items."""

    @pytest.mark.asyncio
    async def test_merges_votes_and_metadata_into_canonical_item(self) -> None:
        db = AsyncMock()
        db.flush = AsyncMock()
        db.delete = AsyncMock()

        source = make_feedback_item(id="source-id", status="open", vote_count=1)
        target = make_feedback_item(id="target-id", status="archived", vote_count=2)
        source.description = "Source description"
        source.resolution_note = "Source resolution"
        source.linked_task_id = "task-123"
        source.created_by_session_id = "sess-1"

        target.description = "Target description"
        target.resolution_note = None
        target.linked_task_id = None
        target.created_by_session_id = None

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [source, target]
        count_result = MagicMock()
        count_result.scalar_one.return_value = 3
        db.execute.side_effect = [select_result, count_result, MagicMock()]

        source_votes = [
            make_feedback_vote(id="source-vote", feedback_item_id="source-id", session_id="sess-1", comment="new context"),
            make_feedback_vote(id="dup-vote", feedback_item_id="source-id", session_id="sess-2", comment="duplicate context"),
        ]
        target_votes = [
            make_feedback_vote(id="target-vote", feedback_item_id="target-id", session_id="sess-2", comment="existing context"),
            make_feedback_vote(id="target-vote-2", feedback_item_id="target-id", session_id="sess-3"),
        ]

        with patch(
            "app.services.feedback_storage.get_feedback_votes",
            new_callable=AsyncMock,
            side_effect=[source_votes, target_votes],
        ):
            merged = await merge_feedback_items(
                db,
                source_item_id="source-id",
                target_item_id="target-id",
            )

        assert merged is target
        assert target.vote_count == 3
        assert target.status == "open"
        assert target.linked_task_id == "task-123"
        assert target.created_by_session_id == "sess-1"
        assert "Source description" in (target.description or "")
        assert "Source resolution" in (target.resolution_note or "")
        assert source_votes[0].feedback_item_id == "target-id"
        assert "duplicate context" in (target_votes[0].comment or "")
        db.delete.assert_any_await(source_votes[1])
        db.delete.assert_any_await(source)

    @pytest.mark.asyncio
    async def test_rejects_merging_item_into_itself(self) -> None:
        db = AsyncMock()

        with pytest.raises(ValueError, match="Cannot merge"):
            await merge_feedback_items(
                db,
                source_item_id="same-id",
                target_item_id="same-id",
            )


class TestFeedbackLifecycleCleanup:
    """Tests for archive and purge helpers."""

    @pytest.mark.asyncio
    async def test_archive_stale_feedback_items_returns_rowcount(self) -> None:
        db = AsyncMock()
        db.execute.return_value = MagicMock(rowcount=4)

        archived = await archive_stale_feedback_items(db, older_than_days=21)

        assert archived == 4

    @pytest.mark.asyncio
    async def test_purge_old_archived_feedback_items_deletes_selected_rows(self) -> None:
        db = AsyncMock()
        db.flush = AsyncMock()

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = ["item-1", "item-2"]
        db.execute.side_effect = [select_result, MagicMock(), MagicMock()]

        purged = await purge_old_archived_feedback_items(
            db,
            older_than_days=120,
            max_vote_count=1,
        )

        assert purged == 2


class TestGetComponentFeedback:
    """Tests for get_component_feedback."""

    @pytest.mark.asyncio
    async def test_returns_component_view(self) -> None:
        db = AsyncMock()

        # First call: search_feedback_items (via db.execute for the SELECT)
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = [
            make_feedback_item(component_id="sf.cli")
        ]

        # Second call: stats query
        stats_result = MagicMock()
        stats_result.mappings.return_value.one.return_value = {
            "total": 5,
            "open_count": 3,
            "resolved_count": 2,
            "friction_count": 2,
            "idea_count": 1,
            "improvement_count": 1,
            "praise_count": 1,
        }

        db.execute.side_effect = [items_result, stats_result]

        result = await get_component_feedback(db, "sf.cli")

        assert result["component_id"] == "sf.cli"
        assert result["stats"]["total"] == 5
        assert len(result["items"]) == 1
