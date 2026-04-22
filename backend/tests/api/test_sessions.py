"""Tests for sessions API endpoints."""

from collections import deque
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.models import CLAUDE_SONNET
from app.db import get_db
from app.main import app
from tests.conftest import APITestClient


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def client(mock_session: AsyncMock) -> Generator[APITestClient]:
    """Test client with mocked database and source headers."""

    async def override_get_db() -> AsyncGenerator[AsyncMock]:
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    yield APITestClient(app)
    app.dependency_overrides.clear()


class TestCreateSession:
    """Tests for POST /api/sessions."""

    @patch(
        "app.constants.VALID_PROJECT_IDS",
        frozenset({"test-project"}),
    )
    def test_create_session_success(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test creating a new session."""

        # Set up refresh to populate timestamps
        def set_timestamps(obj: Any) -> None:
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        mock_session.refresh.side_effect = set_timestamps

        response = client.post(
            "/api/sessions",
            json={
                "project_id": "test-project",
                "provider": "claude",
                "model": CLAUDE_SONNET,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["project_id"] == "test-project"
        assert data["provider"] == "claude"
        assert data["model"] == CLAUDE_SONNET
        assert data["status"] == "active"
        assert data["messages"] == []
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()

    def test_create_session_missing_provider(self, client: APITestClient) -> None:
        """Test validation error for missing provider."""
        response = client.post(
            "/api/sessions",
            json={"project_id": "test", "model": CLAUDE_SONNET},
        )
        assert response.status_code == 422

    def test_create_session_missing_model(self, client: APITestClient) -> None:
        """Test validation error for missing model."""
        response = client.post(
            "/api/sessions",
            json={"project_id": "test", "provider": "claude"},
        )
        assert response.status_code == 422


class TestGetSession:
    """Tests for GET /api/sessions/{session_id}."""

    def test_get_session_success(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test getting a session with messages."""
        # Create mock session object
        mock_db_session = MagicMock()
        mock_db_session.id = "test-session-123"
        mock_db_session.project_id = "test-project"
        mock_db_session.provider = "claude"
        mock_db_session.model = CLAUDE_SONNET
        mock_db_session.status = "active"
        mock_db_session.agent_slug = None
        mock_db_session.session_type = "completion"
        mock_db_session.client_id = "client-123"
        mock_db_session.request_source = "codex-transcript-sync"
        mock_db_session.workstream_status = "completed_ready_for_closure"
        mock_db_session.summary_oneliner = "Closed the loop on session detail observability"
        mock_db_session.models_used = [CLAUDE_SONNET, "codex/gpt-5.4"]
        mock_db_session.providers_used = ["claude", "codex"]
        mock_db_session.provider_metadata = {
            "requested_model": CLAUDE_SONNET,
            "requested_provider": "claude",
            "effective_model": "codex/gpt-5.4",
            "effective_provider": "codex",
            "fallback_used": True,
            "fallback_reason": "TimeoutError: primary timed out",
            "source_client": "summitflow/codex-session-sync",
            "source_path": "/home/kasadis/bin/codex-session-sync.py",
            "live_activity": {
                "phase": "reading_file",
                "status": "active",
                "summary": "Reading frontend/src/app/persona/components/ActivityTimeline.tsx",
                "last_event_at": "2026-01-06T10:00:00+00:00",
                "last_model_activity_at": "2026-01-06T10:00:00+00:00",
                "last_event_type": "tool_use",
                "last_tool_name": "Read",
                "files_touched": [],
                "outstanding_tool_calls": 1,
                "tool_calls_count": 1,
            },
        }
        mock_db_session.created_at = datetime(2026, 1, 6, 10, 0, 0)
        mock_db_session.updated_at = datetime(2026, 1, 6, 10, 0, 0)

        # Create mock events (replacing old messages)
        mock_event = MagicMock()
        mock_event.id = "1"
        mock_event.event_type = "user_message"
        mock_event.turn = 1
        mock_event.sequence = 1
        mock_event.role = "user"
        mock_event.content = "Hello"
        mock_event.input_tokens = 5
        mock_event.output_tokens = 0
        mock_event.model = CLAUDE_SONNET
        mock_event.model_used = CLAUDE_SONNET
        mock_event.agent_slug = "coder"
        mock_event.agent_id = "1"
        mock_event.agent_name = "Coder"
        mock_event.tool_name = None
        mock_event.tool_input = None
        mock_event.tool_output = None
        mock_event.tokens = None
        mock_event.duration_ms = None
        mock_event.created_at = datetime(2026, 1, 6, 10, 0, 0)

        mock_non_message_event = MagicMock()
        mock_non_message_event.id = "2"
        mock_non_message_event.event_type = "error"
        mock_non_message_event.turn = 1
        mock_non_message_event.sequence = 2
        mock_non_message_event.role = None
        mock_non_message_event.content = "Tool failed"
        mock_non_message_event.input_tokens = 0
        mock_non_message_event.output_tokens = 0
        mock_non_message_event.model = CLAUDE_SONNET
        mock_non_message_event.model_used = CLAUDE_SONNET
        mock_non_message_event.agent_slug = None
        mock_non_message_event.agent_id = None
        mock_non_message_event.agent_name = None
        mock_non_message_event.tool_name = None
        mock_non_message_event.tool_input = None
        mock_non_message_event.tool_output = None
        mock_non_message_event.tokens = None
        mock_non_message_event.duration_ms = None
        mock_non_message_event.created_at = datetime(2026, 1, 6, 10, 0, 1)
        mock_db_session.events = [mock_event, mock_non_message_event]

        # Session query result
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = mock_db_session

        # Token totals query result (0, 0)
        mock_token_totals_result = MagicMock()
        mock_token_totals_result.one.return_value = (0, 0)

        # Latest context query result (None - no context yet)
        mock_latest_context_result = MagicMock()
        mock_latest_context_result.scalar_one_or_none.return_value = None

        # Agent display name resolution query result
        mock_agent_names_result = MagicMock()
        mock_agent_names_result.all.return_value = []

        # DB query order for GET /api/sessions/{id}:
        #   (1) get_session_with_events         — scalar_one_or_none → Session ORM object
        #   (2) get_session_token_totals        — .one() → (input_tokens, output_tokens) tuple
        #       (called inside calculate_context_usage)
        #   (3) latest CostLog input_tokens     — scalar_one_or_none → int | None
        #       (called inside calculate_context_usage)
        #   (4) _resolve_agent_display_names    — .all() → list[Row]
        #   (5) child session count query       — scalars().all() → list[Session]
        #   (6) query_project_ownership         — .all() → list[Row]
        #   (7) query_project_active_specialists — .all() → list[Row]
        #
        # Using a deque-based dispatcher keeps the ordered responses explicit and avoids
        # StopIteration when _resolve_agent_display_names is invoked more than once — any
        # extra calls fall back to mock_agent_names_result instead of exhausting the queue.
        _call_queue: deque[MagicMock] = deque(
            [mock_session_result, mock_token_totals_result, mock_latest_context_result, mock_agent_names_result]
        )

        def _execute_side_effect(*args: object, **kwargs: object) -> MagicMock:
            return _call_queue.popleft() if _call_queue else mock_agent_names_result

        mock_session.execute.side_effect = _execute_side_effect

        response = client.get("/api/sessions/test-session-123")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-session-123"
        assert data["model"] == "codex/gpt-5.4"
        assert data["provider"] == "codex"
        assert data["requested_model"] == CLAUDE_SONNET
        assert data["effective_model"] == "codex/gpt-5.4"
        assert data["fallback_used"] is True
        assert data["fallback_reason"] == "TimeoutError: primary timed out"
        assert data["client_id"] == "client-123"
        assert data["request_source"] == "codex-transcript-sync"
        assert data["source_client"] == "summitflow/codex-session-sync"
        assert data["source_path"] == "/home/kasadis/bin/codex-session-sync.py"
        assert data["live_activity"]["phase"] == "reading_file"
        assert data["live_activity"]["health"] in {"quiet", "stalled", "active"}
        assert data["workstream_status"] == "completed_ready_for_closure"
        assert data["summary_oneliner"] == "Closed the loop on session detail observability"
        assert data["message_count"] == 1
        assert data["event_count"] == 2
        assert len(data["messages"]) == 1
        assert data["messages"][0]["content"] == "Hello"
        # Verify context_usage is included
        assert "context_usage" in data
        assert data["context_usage"]["used_tokens"] == 0
        assert data["context_usage"]["limit_tokens"] == 1050000
        # Guard against silent query drift: if a query is added or removed this will
        # surface as a clear assertion failure rather than an opaque StopIteration.
        assert mock_session.execute.call_count == 7, (
            f"Expected 7 DB queries, got {mock_session.execute.call_count} "
            "— update this test if a query was added or removed"
        )

    def test_get_session_not_found(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test 404 for non-existent session."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = client.get("/api/sessions/nonexistent-id")

        assert response.status_code == 404
        assert response.json()["message"] == "Session not found"


class TestDeleteSession:
    """Tests for DELETE /api/sessions/{session_id}."""

    def test_delete_session_success(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test successfully deleting a session."""
        mock_db_session = MagicMock()
        mock_db_session.id = "test-session-123"
        mock_db_session.status = "active"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_db_session
        mock_session.execute.return_value = mock_result

        response = client.delete("/api/sessions/test-session-123")

        assert response.status_code == 204
        # Now does hard delete instead of soft delete
        mock_session.delete.assert_awaited_once_with(mock_db_session)
        mock_session.commit.assert_awaited_once()

    def test_delete_session_not_found(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test 404 when deleting non-existent session."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = client.delete("/api/sessions/nonexistent-id")

        assert response.status_code == 404


class TestListSessions:
    """Tests for GET /api/sessions."""

    def test_list_sessions_empty(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test listing sessions when none exist."""
        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        # Mock list query
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []

        mock_lane_result = MagicMock()
        mock_lane_result.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_list_result, mock_lane_result, mock_lane_result]
        )

        response = client.get("/api/sessions")

        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 20

    def test_list_sessions_with_results(
        self,
        client: APITestClient,
        mock_session: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """Test listing sessions with results."""
        # Create mock session
        mock_db_session = MagicMock()
        mock_db_session.id = "session-1"
        mock_db_session.project_id = "test-project"
        mock_db_session.provider = "claude"
        mock_db_session.model = CLAUDE_SONNET
        mock_db_session.status = "active"
        mock_db_session.agent_slug = None
        mock_db_session.session_type = "completion"
        mock_db_session.summary_oneliner = None
        mock_db_session.client_id = "client-123"
        mock_db_session.request_source = "codex-transcript-sync"
        mock_db_session.models_used = [CLAUDE_SONNET, "codex/gpt-5.4"]
        mock_db_session.providers_used = ["claude", "codex"]
        mock_db_session.parent_session_id = "parent-1"
        mock_db_session.external_id = "task-123"
        mock_db_session.current_branch = "task-123/main"
        mock_db_session.workstream_status = "authoritative"
        mock_db_session.provider_metadata = {
            "cwd": str(tmp_path),
            "requested_model": CLAUDE_SONNET,
            "requested_provider": "claude",
            "effective_model": "codex/gpt-5.4",
            "effective_provider": "codex",
            "fallback_used": True,
            "fallback_reason": "TimeoutError: primary timed out",
            "source_client": "summitflow/codex-session-sync",
            "source_path": "/home/kasadis/bin/codex-session-sync.py",
            "live_activity": {
                "phase": "waiting_for_model",
                "status": "active",
                "summary": "Waiting for model after Bash",
                "last_event_at": "2026-01-06T10:00:00+00:00",
                "last_model_activity_at": "2026-01-06T10:00:00+00:00",
                "last_event_type": "tool_result",
                "files_touched": ["frontend/src/app/persona/components/ActivityTimeline.tsx"],
                "outstanding_tool_calls": 0,
                "tool_calls_count": 2,
            },
        }
        mock_db_session.created_at = datetime(2026, 1, 6, 10, 0, 0)
        mock_db_session.updated_at = datetime(2026, 1, 6, 10, 0, 0)

        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        # Mock list query
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [mock_db_session]

        # Mock message count query
        mock_msg_count_result = MagicMock()
        mock_msg_count_result.all.return_value = [("session-1", 2)]

        # Mock total event count query
        mock_event_count_result = MagicMock()
        mock_event_count_result.all.return_value = [("session-1", 5)]

        # Mock token stats query
        mock_token_stats_result = MagicMock()
        mock_token_stats_result.all.return_value = [
            ("session-1", "user", 100),
            ("session-1", "assistant", 200),
        ]

        mock_lane_result = MagicMock()
        mock_lane_result.all.return_value = []

        _call_queue: deque[MagicMock] = deque(
            [
                mock_count_result,
                mock_list_result,
                mock_msg_count_result,
                mock_event_count_result,
                mock_token_stats_result,
                mock_lane_result,
                mock_lane_result,
            ]
        )

        async def _execute_side_effect(*args: object, **kwargs: object) -> MagicMock:
            return _call_queue.popleft()

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)

        response = client.get("/api/sessions")

        assert response.status_code == 200
        data = response.json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["id"] == "session-1"
        assert data["sessions"][0]["model"] == "codex/gpt-5.4"
        assert data["sessions"][0]["provider"] == "codex"
        assert data["sessions"][0]["requested_model"] == CLAUDE_SONNET
        assert data["sessions"][0]["effective_model"] == "codex/gpt-5.4"
        assert data["sessions"][0]["fallback_used"] is True
        assert data["sessions"][0]["live_activity"]["phase"] == "waiting_for_model"
        assert data["sessions"][0]["live_activity"]["tool_calls_count"] == 2
        assert data["sessions"][0]["message_count"] == 2
        assert data["sessions"][0]["event_count"] == 5
        assert data["sessions"][0]["total_input_tokens"] == 100
        assert data["sessions"][0]["total_output_tokens"] == 200
        assert data["sessions"][0]["parent_session_id"] == "parent-1"
        assert data["sessions"][0]["external_id"] == "task-123"
        assert data["sessions"][0]["client_id"] == "client-123"
        assert data["sessions"][0]["request_source"] == "codex-transcript-sync"
        assert data["sessions"][0]["source_client"] == "summitflow/codex-session-sync"
        assert data["sessions"][0]["source_path"] == "/home/kasadis/bin/codex-session-sync.py"
        assert data["sessions"][0]["current_branch"] == "task-123/main"
        assert data["sessions"][0]["working_dir"] == str(tmp_path)
        assert data["sessions"][0]["workstream_status"] == "authoritative"
        assert data["total"] == 1

    def test_list_sessions_marks_checkout_from_cwd(
        self,
        client: APITestClient,
        mock_session: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """Test session list derives checkout identity from cwd metadata."""
        main_repo = tmp_path / "repo"
        checkout = tmp_path / "checkouts" / "task-123"
        gitdir = main_repo / ".git" / "checkouts" / "task-123"
        gitdir.mkdir(parents=True)
        checkout.mkdir(parents=True)
        (checkout / ".git").write_text(f"gitdir: {gitdir}\n")

        mock_db_session = MagicMock()
        mock_db_session.id = "session-1"
        mock_db_session.project_id = "test-project"
        mock_db_session.provider = "claude"
        mock_db_session.model = CLAUDE_SONNET
        mock_db_session.status = "active"
        mock_db_session.agent_slug = None
        mock_db_session.session_type = "completion"
        mock_db_session.summary_oneliner = None
        mock_db_session.client_id = None
        mock_db_session.request_source = None
        mock_db_session.models_used = [CLAUDE_SONNET]
        mock_db_session.providers_used = ["claude"]
        mock_db_session.parent_session_id = None
        mock_db_session.external_id = "task-123"
        mock_db_session.current_branch = "task-123/main"
        mock_db_session.workstream_status = "authoritative"
        mock_db_session.provider_metadata = {"cwd": str(checkout)}
        mock_db_session.created_at = datetime(2026, 1, 6, 10, 0, 0)
        mock_db_session.updated_at = datetime(2026, 1, 6, 10, 0, 0)

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [mock_db_session]

        mock_msg_count_result = MagicMock()
        mock_msg_count_result.all.return_value = [("session-1", 1)]

        mock_event_count_result = MagicMock()
        mock_event_count_result.all.return_value = [("session-1", 1)]

        mock_token_stats_result = MagicMock()
        mock_token_stats_result.all.return_value = []

        mock_lane_result = MagicMock()
        mock_lane_result.all.return_value = []

        _call_queue: deque[MagicMock] = deque(
            [
                mock_count_result,
                mock_list_result,
                mock_msg_count_result,
                mock_event_count_result,
                mock_token_stats_result,
                mock_lane_result,
                mock_lane_result,
            ]
        )

        async def _execute_side_effect(*args: object, **kwargs: object) -> MagicMock:
            return _call_queue.popleft()

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)

        response = client.get("/api/sessions")

        assert response.status_code == 200
        data = response.json()
        assert data["sessions"][0]["working_dir"] == str(checkout)
        assert data["sessions"][0]["event_count"] == 1

    def test_list_sessions_filter_by_project(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test filtering by project_id."""
        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        # Mock list query
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []

        mock_lane_result = MagicMock()
        mock_lane_result.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_list_result, mock_lane_result, mock_lane_result]
        )

        response = client.get("/api/sessions?project_id=my-project")

        assert response.status_code == 200

    def test_list_sessions_filter_by_status(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test filtering by status."""
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(side_effect=[mock_count_result, mock_list_result])

        response = client.get("/api/sessions?status=active")

        assert response.status_code == 200

    @patch("app.api.sessions.build_project_lane_session_ids", new_callable=AsyncMock)
    @patch("app.api.sessions.list_sessions_with_stats", new_callable=AsyncMock)
    def test_list_sessions_filter_by_external_id(
        self,
        mock_list_sessions: AsyncMock,
        mock_lane_session_ids: AsyncMock,
        client: APITestClient,
    ) -> None:
        """Test filtering by linked external_id."""
        mock_list_sessions.return_value = ([], 0, {}, {}, {})
        mock_lane_session_ids.return_value = (set(), set())

        response = client.get("/api/sessions?external_id=task-12345678")

        assert response.status_code == 200
        mock_list_sessions.assert_awaited_once()
        await_args = mock_list_sessions.await_args
        assert await_args is not None
        assert await_args.kwargs["external_id"] == "task-12345678"

    def test_list_sessions_pagination(self, client: APITestClient, mock_session: AsyncMock) -> None:
        """Test pagination parameters."""
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 50

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []

        mock_lane_result = MagicMock()
        mock_lane_result.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_list_result, mock_lane_result, mock_lane_result]
        )

        response = client.get("/api/sessions?page=3&page_size=10")

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 3
        assert data["page_size"] == 10
        assert data["total"] == 50
