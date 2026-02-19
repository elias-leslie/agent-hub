"""Tests for session branching API endpoints.

Tests the fork/promote foundation implemented in #14.
Note: Full Mutex pattern (lock, apply patches, execute, revert) was deferred.
"""

from app.api.sessions import (
    SessionForkRequest,
    SessionForkResponse,
    SessionPromoteRequest,
    SessionPromoteResponse,
)
from app.constants.models import CLAUDE_SONNET
from app.models import Session


class TestSessionBranchingModels:
    """Tests for session branching Pydantic models."""

    def test_fork_request_default(self) -> None:
        """Fork request with defaults should have None fork_at_turn."""
        request = SessionForkRequest()
        assert request.fork_at_turn is None

    def test_fork_request_with_turn(self) -> None:
        """Fork request should accept fork_at_turn."""
        request = SessionForkRequest(fork_at_turn=5)
        assert request.fork_at_turn == 5

    def test_fork_response_fields(self) -> None:
        """Fork response should have all required fields."""
        response = SessionForkResponse(
            id="new-session-id",
            parent_session_id="parent-id",
            fork_point_turn=3,
            message_count=6,
            branch_status="active",
        )
        assert response.id == "new-session-id"
        assert response.parent_session_id == "parent-id"
        assert response.fork_point_turn == 3
        assert response.message_count == 6
        assert response.branch_status == "active"

    def test_promote_request_default(self) -> None:
        """Promote request should default to discarding siblings."""
        request = SessionPromoteRequest()
        assert request.discard_siblings is True

    def test_promote_request_keep_siblings(self) -> None:
        """Promote request should allow keeping siblings."""
        request = SessionPromoteRequest(discard_siblings=False)
        assert request.discard_siblings is False

    def test_promote_response_fields(self) -> None:
        """Promote response should have all required fields."""
        response = SessionPromoteResponse(
            id="session-id",
            branch_status="promoted",
            discarded_siblings=["sibling-1", "sibling-2"],
            patches_applied=3,
        )
        assert response.id == "session-id"
        assert response.branch_status == "promoted"
        assert response.discarded_siblings == ["sibling-1", "sibling-2"]
        assert response.patches_applied == 3


class TestSessionBranchingDatabaseModel:
    """Tests for Session model branching fields."""

    def test_session_has_branching_fields(self) -> None:
        """Session model should have branching fields."""
        session = Session(
            id="test-session",
            project_id="test-project",
            provider="claude",
            model=CLAUDE_SONNET,
            status="active",
        )

        assert hasattr(session, "parent_session_id")
        assert hasattr(session, "fork_point_turn")
        assert hasattr(session, "pending_patches")
        assert hasattr(session, "branch_status")
        assert hasattr(session, "manual_outcome")

    def test_session_defaults(self) -> None:
        """Session branching fields should have correct defaults."""
        session = Session(
            id="test-session",
            project_id="test-project",
            provider="claude",
            model=CLAUDE_SONNET,
            status="active",
        )

        assert session.parent_session_id is None
        assert session.fork_point_turn is None
        assert session.pending_patches is None
        assert session.branch_status is None
        assert session.manual_outcome is None

    def test_session_with_branching(self) -> None:
        """Session can be created with branching fields."""
        session = Session(
            id="forked-session",
            project_id="test-project",
            provider="claude",
            model=CLAUDE_SONNET,
            status="active",
            parent_session_id="parent-session",
            fork_point_turn=5,
            branch_status="active",
        )

        assert session.parent_session_id == "parent-session"
        assert session.fork_point_turn == 5
        assert session.branch_status == "active"


class TestBranchingWorkflow:
    """Tests for branching workflow logic."""

    def test_fork_point_turn_validation(self) -> None:
        """Fork point turn should be non-negative."""
        request = SessionForkRequest(fork_at_turn=0)
        assert request.fork_at_turn == 0

        request = SessionForkRequest(fork_at_turn=10)
        assert request.fork_at_turn == 10

    def test_branch_status_values(self) -> None:
        """Branch status should be one of active/promoted/discarded."""
        for status in ["active", "promoted", "discarded"]:
            session = Session(
                id=f"session-{status}",
                project_id="test-project",
                provider="claude",
                model=CLAUDE_SONNET,
                status="active",
                branch_status=status,
            )
            assert session.branch_status == status

    def test_outcome_tracking_fields(self) -> None:
        """Outcome tracking fields should accept valid values."""
        session = Session(
            id="outcome-session",
            project_id="test-project",
            provider="claude",
            model=CLAUDE_SONNET,
            status="active",
            parent_session_id="parent",
            manual_outcome="selected",
        )

        assert session.manual_outcome == "selected"
