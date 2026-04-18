"""Tests for heartbeat prompt builder — git_status_summary and prompt assembly."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workflows._heartbeat_data import (
    _build_workstream_next_action,
    _classify_workstream_lane,
    _collect_agent_hub_heartbeat_state,
    _collect_summitflow_heartbeat_state,
    _fetch_cleanup_status,
    _fetch_git_status_compact,
    _fetch_recently_completed_sessions_section,
    _fetch_task_overview_raw,
    _get_active_specialist_inventory,
    _get_active_work_summary,
    _get_cleanup_status_summary,
    _get_git_status_summary,
    _get_protection_status_summary,
    _get_recent_heartbeat_digest,
    _get_recent_idle_improvement_history,
    _get_workstream_inventory,
    _query_active_sessions_for_heartbeat,
    _query_active_specialist_sessions,
    _query_recent_workstream_sessions,
)
from app.workflows._heartbeat_recall import HeartbeatRecallSections


def _mock_async_session_with_rows(rows: list[object]):
    """Create an async_session context manager whose execute().all() yields rows."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    mock_db.execute.return_value = mock_result

    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session, mock_db


def _mock_async_session_with_scalars(rows: list[object]):
    """Create an async_session context manager whose execute().scalars().all() yields rows."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = rows
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result

    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session, mock_db


class _FakeGitStatusResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeGitStatusResponse) -> None:
        self._response = response
        self.requested_urls: list[str] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str) -> _FakeGitStatusResponse:
        self.requested_urls.append(url)
        return self._response


class TestGetGitStatusSummary:
    """Tests for _get_git_status_summary."""

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_git_status_rows", new_callable=AsyncMock)
    async def test_returns_xml_block(self, mock_fetch: AsyncMock) -> None:
        """Returns <git_state> XML when compact git status has content."""
        from app.services.git_status_summary import RepoGitStatus

        mock_fetch.return_value = [
            RepoGitStatus(
                project_id="summitflow",
                branch="main",
                state="clean",
                uncommitted=0,
                ahead=0,
                behind=0,
            ),
            RepoGitStatus(
                project_id="agent-hub",
                branch="main",
                state="dirty",
                uncommitted=3,
                ahead=1,
                behind=0,
            ),
        ]
        result = await _get_git_status_summary()

        assert result.startswith("\n<git_state>")
        assert result.endswith("</git_state>")
        assert "GIT[2]" in result
        assert "ACTIONABLE-GIT[1]" in result
        assert "agent-hub" in result

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_git_status_rows", new_callable=AsyncMock, return_value=[])
    async def test_empty_when_no_git_state(self, mock_fetch: AsyncMock) -> None:
        """Returns empty when compact git status output is empty."""
        result = await _get_git_status_summary()
        assert result == ""

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_git_status_rows", new_callable=AsyncMock)
    async def test_filters_to_target_project(self, mock_fetch: AsyncMock) -> None:
        from app.services.git_status_summary import RepoGitStatus

        mock_fetch.return_value = [
            RepoGitStatus(
                project_id="agent-hub",
                branch="main",
                state="dirty",
                uncommitted=3,
                ahead=1,
                behind=0,
            )
        ]

        result = await _get_git_status_summary("agent-hub")

        assert "agent-hub" in result
        assert "summitflow" not in result
        assert "ACTIONABLE-GIT[1]" in result

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_git_status_rows", new_callable=AsyncMock)
    async def test_builds_git_state_from_structured_rows(self, mock_fetch_rows: AsyncMock) -> None:
        from app.services.git_status_summary import RepoGitStatus

        mock_fetch_rows.return_value = [
            RepoGitStatus(
                project_id="agent-hub",
                branch="main",
                state="dirty",
                uncommitted=3,
                ahead=1,
                behind=0,
            )
        ]

        result = await _get_git_status_summary()

        assert "GIT[1]" in result
        assert "agent-hub       main            dirty   uncommitted:3 ahead:1 behind:0" in result
        assert "ACTIONABLE-GIT[1]" in result


class TestFetchGitStatusCompact:
    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._read_project_api_url", return_value="http://localhost:8001/api")
    @patch("app.workflows._heartbeat_data.httpx.AsyncClient")
    async def test_renders_compact_output_from_api_payload(
        self,
        mock_client_cls: MagicMock,
        _mock_read_api_url: MagicMock,
    ) -> None:
        fake_client = _FakeAsyncClient(
            _FakeGitStatusResponse(
                {
                    "repositories": [
                        {
                            "project_id": "summitflow",
                            "branch": "main",
                            "state": "clean",
                            "uncommitted": 0,
                            "ahead": 0,
                            "behind": 0,
                        },
                        {
                            "project_id": "agent-hub",
                            "branch": "main",
                            "state": "dirty",
                            "uncommitted": 2,
                            "ahead": 1,
                            "behind": 0,
                        },
                    ]
                }
            )
        )
        mock_client_cls.return_value = fake_client

        result = await _fetch_git_status_compact()

        assert result == (
            "GIT[2]\n"
            "summitflow      main            clean   uncommitted:0 ahead:0 behind:0\n"
            "agent-hub       main            dirty   uncommitted:2 ahead:1 behind:0"
        )
        assert fake_client.requested_urls == ["http://localhost:8001/api/git/status"]


class TestCollectSummitflowHeartbeatState:
    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_recent_failed_tasks", new_callable=AsyncMock)
    @patch("app.workflows._heartbeat_data._fetch_git_status_rows", new_callable=AsyncMock)
    @patch("app.workflows._heartbeat_data._fetch_cleanup_status_response", new_callable=AsyncMock)
    @patch("app.workflows._heartbeat_data._fetch_task_overview_response", new_callable=AsyncMock)
    async def test_collects_canonical_sections_once(
        self,
        mock_task_overview: AsyncMock,
        mock_cleanup_status: AsyncMock,
        mock_git_rows: AsyncMock,
        mock_recent_failed: AsyncMock,
    ) -> None:
        from app.services.git_status_summary import RepoGitStatus

        mock_task_overview.return_value = {
            "raw": "READY-ALL[1]\n...",
            "payload": {"projects": [{"project_id": "agent-hub"}]},
        }
        mock_cleanup_status.return_value = {
            "compact": "CLEANUP[all]:repos=1 needs_cleanup=0",
            "payload": {"summary": {"needs_cleanup": 0}},
        }
        mock_git_rows.return_value = [
            RepoGitStatus(
                project_id="agent-hub",
                branch="main",
                state="clean",
                uncommitted=0,
                ahead=0,
                behind=0,
            )
        ]
        mock_recent_failed.return_value = [
            {
                "id": "task-failed-1",
                "project_id": "agent-hub",
                "title": "Fix failed task",
            }
        ]

        state = await _collect_summitflow_heartbeat_state("agent-hub")

        assert state.task_overview_response == mock_task_overview.return_value
        assert state.task_overview_payload == {"projects": [{"project_id": "agent-hub"}]}
        assert state.task_overview_raw == "READY-ALL[1]\n..."
        assert state.cleanup_status_response == mock_cleanup_status.return_value
        assert len(state.git_status_rows) == 1
        assert state.recent_failed_tasks == mock_recent_failed.return_value
        mock_task_overview.assert_awaited_once_with()
        mock_cleanup_status.assert_awaited_once_with("agent-hub")
        mock_git_rows.assert_awaited_once_with("agent-hub")
        mock_recent_failed.assert_awaited_once_with("agent-hub")

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_recent_failed_tasks", new_callable=AsyncMock, return_value=[])
    @patch("app.workflows._heartbeat_data._fetch_git_status_rows", new_callable=AsyncMock, return_value=[])
    @patch("app.workflows._heartbeat_data._fetch_cleanup_status_response", new_callable=AsyncMock, return_value=None)
    @patch("app.workflows._heartbeat_data._fetch_task_overview_response", new_callable=AsyncMock, return_value=None)
    async def test_handles_missing_state_gracefully(
        self,
        _mock_task_overview: AsyncMock,
        _mock_cleanup_status: AsyncMock,
        _mock_git_rows: AsyncMock,
        _mock_recent_failed: AsyncMock,
    ) -> None:
        state = await _collect_summitflow_heartbeat_state()

        assert state.task_overview_response is None
        assert state.task_overview_payload is None
        assert state.task_overview_raw == ""
        assert state.cleanup_status_response is None
        assert state.git_status_rows == []
        assert state.recent_failed_tasks == []


class TestCollectAgentHubHeartbeatState:
    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._query_recent_workstream_sessions", new_callable=AsyncMock)
    @patch("app.workflows._heartbeat_data._query_active_specialist_sessions", new_callable=AsyncMock)
    @patch("app.workflows._heartbeat_data._query_active_sessions_for_heartbeat", new_callable=AsyncMock)
    async def test_collects_canonical_sections_once(
        self,
        mock_active_sessions: AsyncMock,
        mock_specialists: AsyncMock,
        mock_workstreams: AsyncMock,
    ) -> None:
        mock_active_sessions.return_value = [{"session_id": "s-1"}]
        mock_specialists.return_value = [{"agent_slug": "reviewer"}]
        mock_workstreams.return_value = [{"task_id": "task-1"}]

        state = await _collect_agent_hub_heartbeat_state("agent-hub")

        assert state.active_sessions == [{"session_id": "s-1"}]
        assert state.active_specialist_sessions == [{"agent_slug": "reviewer"}]
        assert state.workstream_rows == [{"task_id": "task-1"}]
        mock_active_sessions.assert_awaited_once()
        mock_specialists.assert_awaited_once()
        mock_workstreams.assert_awaited_once()
        active_await = mock_active_sessions.await_args
        specialists_await = mock_specialists.await_args
        workstreams_await = mock_workstreams.await_args
        assert active_await is not None
        assert specialists_await is not None
        assert workstreams_await is not None
        assert active_await.args == ("agent-hub",)
        assert specialists_await.args == ("agent-hub",)
        assert workstreams_await.args == ("agent-hub",)
        assert active_await.kwargs["now"] == state.collected_at
        assert specialists_await.kwargs["now"] == state.collected_at
        assert workstreams_await.kwargs["now"] == state.collected_at

    @pytest.mark.asyncio
    @patch(
        "app.workflows._heartbeat_data._query_recent_workstream_sessions",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch(
        "app.workflows._heartbeat_data._query_active_specialist_sessions",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch(
        "app.workflows._heartbeat_data._query_active_sessions_for_heartbeat",
        new_callable=AsyncMock,
        return_value=[],
    )
    async def test_handles_missing_state_gracefully(
        self,
        _mock_active_sessions: AsyncMock,
        _mock_specialists: AsyncMock,
        _mock_workstreams: AsyncMock,
    ) -> None:
        state = await _collect_agent_hub_heartbeat_state()

        assert state.active_sessions == []
        assert state.active_specialist_sessions == []
        assert state.workstream_rows == []


class TestQueryRecentWorkstreamSessions:
    @pytest.mark.asyncio
    async def test_filters_to_lane_and_reconciled_rows_and_orders_by_recent_lane_activity(self) -> None:
        now = datetime(2026, 3, 31, 16, 0, tzinfo=UTC)
        session_factory, mock_db = _mock_async_session_with_rows(
            [
                SimpleNamespace(
                    id="sess-1",
                    agent_slug="coder",
                    project_id="a-term",
                    external_id="task-2c2abc80",
                    current_branch="task-2c2abc80/main",
                    provider_metadata={"cwd": "/srv/workspaces/lanes/a-term/task-2c2abc80"},
                    status="completed",
                    workstream_status="authoritative",
                    workstream_note="Selected as authoritative during reconcile",
                    workstream_updated_at=now,
                    created_at=now - timedelta(hours=17),
                    updated_at=now,
                ),
            ]
        )

        with patch("app.db.async_session", session_factory):
            rows = await _query_recent_workstream_sessions(now=now)

        executed_query = str(mock_db.execute.await_args.args[0])
        assert rows[0]["external_id"] == "task-2c2abc80"
        assert "sessions.workstream_status IS NOT NULL" in executed_query
        assert "sessions.external_id LIKE :external_id_1" in executed_query
        assert "sessions.current_branch LIKE :current_branch_1" in executed_query
        assert (
            "coalesce(sessions.workstream_updated_at, sessions.updated_at, sessions.created_at) DESC"
            in executed_query
        )


class TestAppendDynamicSections:
    @pytest.mark.asyncio
    @patch(
        "app.workflows._heartbeat_prompt.build_heartbeat_recall_sections",
        new_callable=AsyncMock,
        return_value=HeartbeatRecallSections(),
    )
    @patch("app.workflows._heartbeat_prompt._get_feedback_summary_section", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_git_status_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_recent_failed_tasks_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_workstream_inventory", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_agent_roster_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_active_specialist_inventory", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_cleanup_status_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_protection_status_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_active_work_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._collect_agent_hub_heartbeat_state", new_callable=AsyncMock)
    @patch("app.workflows._heartbeat_prompt._collect_summitflow_heartbeat_state", new_callable=AsyncMock)
    async def test_threads_canonical_states_into_section_builders(
        self,
        mock_collect_summitflow: AsyncMock,
        mock_collect_agent_hub: AsyncMock,
        mock_active_work: AsyncMock,
        mock_protection: AsyncMock,
        mock_cleanup: AsyncMock,
        mock_active_specialists: AsyncMock,
        mock_roster: AsyncMock,
        mock_workstreams: AsyncMock,
        mock_recent_failed: AsyncMock,
        mock_git: AsyncMock,
        mock_feedback: AsyncMock,
        mock_recall: AsyncMock,
    ) -> None:
        from app.workflows._heartbeat_data import AgentHubHeartbeatState, SummitFlowHeartbeatState
        from app.workflows._heartbeat_prompt import _append_dynamic_sections

        summitflow_state = SummitFlowHeartbeatState(
            task_overview_response={"raw": "READY-ALL[1]", "payload": {"projects": []}},
            cleanup_status_response={"compact": "CLEANUP[all]:repos=0 needs_cleanup=0"},
            git_status_rows=[],
            recent_failed_tasks=[],
        )
        agent_hub_state = AgentHubHeartbeatState(
            collected_at=datetime(2026, 3, 25, tzinfo=UTC),
            active_sessions=[{"session_id": "s-1"}],
            active_specialist_sessions=[{"agent_slug": "reviewer"}],
            workstream_rows=[{"task_id": "task-1"}],
        )
        mock_collect_summitflow.return_value = summitflow_state
        mock_collect_agent_hub.return_value = agent_hub_state

        result = await _append_dynamic_sections("base", "agent-hub", "codex")

        assert result == "base"
        mock_collect_summitflow.assert_awaited_once_with("agent-hub")
        mock_collect_agent_hub.assert_awaited_once_with("agent-hub")
        mock_active_work.assert_awaited_once_with(
            task_overview=None,
            task_overview_payload={"projects": []},
            target_project_id="agent-hub",
            heartbeat_state=summitflow_state,
            agent_hub_state=agent_hub_state,
        )
        mock_protection.assert_awaited_once_with("agent-hub")
        mock_cleanup.assert_awaited_once_with(
            "agent-hub",
            cleanup_status_response=summitflow_state.cleanup_status_response,
            workstream_rows=agent_hub_state.workstream_rows,
        )
        mock_active_specialists.assert_awaited_once_with(
            "agent-hub",
            agent_hub_state=agent_hub_state,
        )
        mock_roster.assert_awaited_once_with()
        mock_workstreams.assert_awaited_once_with(
            "codex",
            task_overview=None,
            task_overview_payload={"projects": []},
            target_project_id="agent-hub",
            heartbeat_state=summitflow_state,
            agent_hub_state=agent_hub_state,
        )
        mock_recent_failed.assert_awaited_once_with(
            "agent-hub",
            heartbeat_state=summitflow_state,
        )
        mock_git.assert_awaited_once_with("agent-hub", git_status_rows=[])
        mock_feedback.assert_awaited_once_with()
        mock_recall.assert_awaited_once_with("agent-hub")


class TestRecentFailedTasksSummary:
    @pytest.mark.asyncio
    async def test_renders_recent_failed_tasks_from_heartbeat_state(self) -> None:
        from app.workflows._heartbeat_orchestrators import _get_recent_failed_tasks_summary
        from app.workflows._heartbeat_state import SummitFlowHeartbeatState

        state = SummitFlowHeartbeatState(
            task_overview_response=None,
            cleanup_status_response=None,
            git_status_rows=[],
            recent_failed_tasks=[
                {
                    "id": "task-1025819f",
                    "project_id": "agent-hub",
                    "title": "Refactor: backend/app/workflows/_heartbeat_data.py",
                    "current_phase": "plan",
                    "last_changed_at": datetime(2026, 4, 1, 22, 9, tzinfo=UTC),
                }
            ],
        )

        result = await _get_recent_failed_tasks_summary("agent-hub", heartbeat_state=state)

        assert result.startswith("\n<recent_failed_tasks>")
        assert "Recent failed tasks: 1" in result
        assert "Follow first: agent-hub | task-1025819f | failed" in result
        assert "task-1025819f" in result
        assert "phase=plan" in result
        assert "Refactor: backend/app/workflows/_heartbeat_data.py" in result
        assert result.endswith("</recent_failed_tasks>")


class TestRecentHeartbeatDigest:
    def test_recent_heartbeat_digest_statuses_match_session_enum(self) -> None:
        from app.models import Session
        from app.workflows._heartbeat_data import _HEARTBEAT_DIGEST_STATUSES

        status_enum_values = getattr(Session.__table__.c.status.type, "enums", [])
        assert set(_HEARTBEAT_DIGEST_STATUSES) <= set(status_enum_values)

    @pytest.mark.asyncio
    async def test_formats_recent_heartbeat_digest_with_cleaned_display_summaries(self) -> None:
        now = datetime.now(UTC)
        session_factory, mock_db = _mock_async_session_with_rows(
            [
                (
                    "hb-1",
                    "agent-hub",
                    "completed",
                    now,
                    "[[P:done]] Patched cleanup truth and passed targeted tests.",
                    {
                        "live_activity": {
                            "summary": "Patched cleanup truth and passed targeted tests.",
                        }
                    },
                ),
                (
                    "hb-2",
                    "agent-hub",
                    "failed",
                    now - timedelta(minutes=5),
                    "Heartbeat failed after guessing an invalid dt pytest path.",
                    {},
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.fetch_session_display_summary_results",
                new_callable=AsyncMock,
                return_value={
                    "hb-1": "Patched cleanup truth and passed targeted tests.",
                    "hb-2": "Heartbeat failed after guessing an invalid dt pytest path.",
                },
            ) as mock_fetch_summaries,
        ):
            result = await _get_recent_heartbeat_digest("agent-hub")

        executed_query = str(mock_db.execute.await_args.args[0])
        assert "<recent_heartbeat_digest>" in result
        assert "Recent heartbeat recall: 2" in result
        assert "completed | agent-hub | Patched cleanup truth and passed targeted tests." in result
        assert "failed | agent-hub | Heartbeat failed after guessing an invalid dt pytest path." in result
        assert "sessions.request_source = :request_source_1" in executed_query
        fetch_await = mock_fetch_summaries.await_args
        assert fetch_await is not None
        candidates = fetch_await.args[1]
        assert [candidate.session_id for candidate in candidates] == ["hb-1", "hb-2"]

    @pytest.mark.asyncio
    async def test_recent_heartbeat_digest_respects_token_budget(self) -> None:
        now = datetime.now(UTC)
        session_factory, _mock_db = _mock_async_session_with_rows(
            [
                ("hb-1", "agent-hub", "completed", now, "First scoped digest row.", {}),
                (
                    "hb-2",
                    "agent-hub",
                    "completed",
                    now - timedelta(minutes=1),
                    "Second scoped digest row.",
                    {},
                ),
                (
                    "hb-3",
                    "agent-hub",
                    "failed",
                    now - timedelta(minutes=2),
                    "Third scoped digest row.",
                    {},
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.fetch_session_display_summary_results",
                new_callable=AsyncMock,
                return_value={
                    "hb-1": "First scoped digest row.",
                    "hb-2": "Second scoped digest row.",
                    "hb-3": "Third scoped digest row.",
                },
            ),
            patch(
                "app.workflows._heartbeat_data.count_tokens",
                side_effect=lambda text: text.count("\n- ") * 100,
            ),
            patch("app.workflows._heartbeat_data._HEARTBEAT_DIGEST_TOKEN_BUDGET", 250),
        ):
            result = await _get_recent_heartbeat_digest("agent-hub")

        assert "Recent heartbeat recall: 2" in result
        assert "First scoped digest row." in result
        assert "Second scoped digest row." in result
        assert "Third scoped digest row." not in result


class TestRecentIdleImprovementHistory:
    @pytest.mark.asyncio
    async def test_formats_recent_idle_heartbeat_slices_with_validation_commands(self) -> None:
        now = datetime.now(UTC)
        session_factory, mock_db = _mock_async_session_with_scalars(
            [
                MagicMock(
                    id="sess-failed-idle",
                    agent_slug="persona",
                    project_id="agent-hub",
                    request_source="heartbeat",
                    status="completed",
                    created_at=now,
                    summary_oneliner=(
                        "Confirmed agent-hub is still clean and idle, but the bounded health "
                        "check failed on an invalid test path."
                    ),
                    summary_files_touched=[],
                    provider_metadata={
                        "live_activity": {
                            "last_validation_command": (
                                "cd /srv/workspaces/projects/agent-hub && "
                                "dt pytest backend/tests/api/test_agents_registry.py"
                            )
                        }
                    },
                ),
                MagicMock(
                    id="sess-idle",
                    agent_slug="persona",
                    project_id="agent-hub",
                    request_source="heartbeat",
                    status="completed",
                    created_at=now - timedelta(minutes=1),
                    summary_oneliner=(
                        "Agent-hub stayed clean and idle after feedback/session mining, "
                        "a passing ah.memory test slice, and a refreshed zero-ready overview."
                    ),
                    summary_files_touched=[],
                    provider_metadata={
                        "live_activity": {
                            "last_validation_command": (
                                "cd /srv/workspaces/projects/agent-hub && "
                                "dt pytest backend/tests/api/test_memory.py -q"
                            )
                        }
                    },
                ),
                MagicMock(
                    id="sess-write",
                    agent_slug="persona",
                    project_id="agent-hub",
                    request_source="heartbeat",
                    status="completed",
                    created_at=now - timedelta(minutes=5),
                    summary_oneliner="Patched cleanup truth and passed targeted tests.",
                    summary_files_touched=["backend/app/workflows/_heartbeat_prompt.py"],
                    provider_metadata={
                        "live_activity": {
                            "last_validation_command": (
                                "cd /srv/workspaces/projects/agent-hub && "
                                "dt pytest backend/tests/workflows/test_heartbeat_prompt.py"
                            )
                        }
                    },
                ),
            ]
        )

        with patch("app.db.async_session", session_factory):
            result = await _get_recent_idle_improvement_history("agent-hub")

        executed_query = str(mock_db.execute.await_args.args[0])
        assert "<recent_idle_improvement_history>" in result
        assert "Recent idle slices: 2" in result
        assert "attempt=`dt pytest backend/tests/api/test_agents_registry.py`" in result
        assert "verify=`dt pytest backend/tests/api/test_memory.py -q`" in result
        assert "ah.memory test slice" in result
        assert "failed on an invalid test path" in result
        assert "Patched cleanup truth" not in result
        assert "sessions.agent_slug = :agent_slug_1" in executed_query

    @pytest.mark.asyncio
    async def test_recent_idle_history_respects_token_budget(self) -> None:
        now = datetime.now(UTC)
        session_factory, _mock_db = _mock_async_session_with_scalars(
            [
                MagicMock(
                    id="sess-idle-1",
                    agent_slug="persona",
                    project_id="agent-hub",
                    request_source="heartbeat",
                    status="completed",
                    created_at=now,
                    summary_oneliner="Agent-hub stayed clean and idle after first bounded slice.",
                    summary_files_touched=[],
                    provider_metadata={
                        "live_activity": {
                            "last_validation_command": (
                                "cd /srv/workspaces/projects/agent-hub && "
                                "dt pytest backend/tests/api/test_memory.py -q"
                            )
                        }
                    },
                ),
                MagicMock(
                    id="sess-idle-2",
                    agent_slug="persona",
                    project_id="agent-hub",
                    request_source="heartbeat",
                    status="completed",
                    created_at=now - timedelta(minutes=1),
                    summary_oneliner="Agent-hub stayed clean and idle after second bounded slice.",
                    summary_files_touched=[],
                    provider_metadata={
                        "live_activity": {
                            "last_validation_command": (
                                "cd /srv/workspaces/projects/agent-hub && "
                                "dt pytest backend/tests/api/test_feedback.py -q"
                            )
                        }
                    },
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.count_tokens",
                side_effect=lambda text: text.count("\n- ") * 100,
            ),
            patch("app.workflows._heartbeat_data._IDLE_HISTORY_TOKEN_BUDGET", 150),
        ):
            result = await _get_recent_idle_improvement_history("agent-hub")

        assert "Recent idle slices: 1" in result
        assert "test_memory.py" in result
        assert "test_feedback.py" not in result


class TestBuildHeartbeatPromptIncludesGitState:
    """Integration: build_heartbeat_prompt includes git_state section."""

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_prompt._get_active_specialist_inventory", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_agent_roster_summary", new_callable=AsyncMock, return_value="")
    @patch(
        "app.workflows._heartbeat_prompt._get_recent_failed_tasks_summary",
        new_callable=AsyncMock,
        return_value="\n<recent_failed_tasks>\nRecent failed tasks: 1\n- agent-hub | task-1025819f | failed | 12m ago | phase=plan | Refactor: backend/app/workflows/_heartbeat_data.py\n</recent_failed_tasks>",
    )
    @patch(
        "app.workflows._heartbeat_prompt._get_protection_status_summary",
        new_callable=AsyncMock,
        return_value="\n<protection_status>\nLATEST bkp-123|completed|8.5MB\nSOURCE:agent-hub|enabled|daily|retention_days:30\n</protection_status>",
    )
    @patch(
        "app.workflows._heartbeat_prompt._get_cleanup_status_summary",
        new_callable=AsyncMock,
        return_value="\n<cleanup_status>\nCLEANUP[all]:repos=2 needs_cleanup=1 checkpoints=1 dirty=0 orphan=1 prunable=0\n</cleanup_status>",
    )
    @patch(
        "app.workflows._heartbeat_prompt._get_git_status_summary",
        new_callable=AsyncMock,
        return_value="\n<git_state>\n[summitflow] test data\n</git_state>",
    )
    @patch(
        "app.workflows._heartbeat_prompt.build_heartbeat_recall_sections",
        new_callable=AsyncMock,
        return_value=HeartbeatRecallSections(),
    )
    @patch("app.workflows._heartbeat_prompt._fetch_task_overview", new_callable=AsyncMock, return_value="")
    @patch(
        "app.workflows._heartbeat_prompt.require_prompt_content",
        new_callable=AsyncMock,
        return_value=(
            "Run your regular heartbeat check. Current time: {timestamp} ({local_time})\n\n"
            "{project_access_summary}\n\n"
            "## Model Review ({model_review_status})\n"
            "- If status is `DUE`, run `review_agent_performance`.\n"
            "- If status is not due, skip model review this heartbeat.\n\n"
            "## Available Tools ({tool_count} total)\n"
            "Beyond bash/read_file/write_file, you have: {persona_tool_list}\n\n"
            "Follow your <heartbeat_instructions> from your system context."
        ),
    )
    @patch("app.workflows._heartbeat_prompt._get_active_work_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_persona_tool_summary", return_value=(5, "tool1, tool2"))
    @patch("app.workflows._heartbeat_prompt.get_project_access_summary", new_callable=AsyncMock, return_value="test")
    @patch("app.workflows._heartbeat_prompt._get_persona_timezone", new_callable=AsyncMock, return_value="UTC")
    async def test_git_state_in_prompt(self, *mocks: MagicMock) -> None:
        from app.workflows._heartbeat_prompt import build_heartbeat_prompt

        prompt = await build_heartbeat_prompt(model_review_due=False, model_review_label="skip")
        assert "<protection_status>" in prompt
        assert "LATEST bkp-123|completed|8.5MB" in prompt
        assert "<cleanup_status>" in prompt
        assert "CLEANUP[all]:repos=2 needs_cleanup=1" in prompt
        assert "<recent_failed_tasks>" in prompt
        assert "task-1025819f" in prompt
        assert "<git_state>" in prompt
        assert "[summitflow] test data" in prompt
        assert "Run your regular heartbeat check." in prompt
        assert "## Model Review (not due — skip)" in prompt
        assert "If status is not due, skip model review this heartbeat." in prompt
        assert "## Available Tools (5 total)" in prompt
        assert "tool1, tool2" in prompt
        assert "Follow your <heartbeat_instructions> from your system context." in prompt

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_prompt._get_active_specialist_inventory", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_agent_roster_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_recent_failed_tasks_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_protection_status_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_cleanup_status_summary", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_prompt._get_git_status_summary", new_callable=AsyncMock, return_value="")
    @patch(
        "app.workflows._heartbeat_prompt.build_heartbeat_recall_sections",
        new_callable=AsyncMock,
        return_value=HeartbeatRecallSections(),
    )
    @patch("app.workflows._heartbeat_prompt._fetch_task_overview", new_callable=AsyncMock, return_value="")
    @patch(
        "app.workflows._heartbeat_prompt.require_prompt_content",
        new_callable=AsyncMock,
        return_value="Tools: {persona_tool_list}",
    )
    @patch("app.workflows._heartbeat_prompt._get_active_work_summary", new_callable=AsyncMock, return_value="")
    @patch(
        "app.workflows._heartbeat_prompt._get_persona_tool_summary",
        return_value=(0, "none; shell-first core tools only"),
    )
    @patch("app.workflows._heartbeat_prompt.get_project_access_summary", new_callable=AsyncMock, return_value="test")
    @patch("app.workflows._heartbeat_prompt._get_persona_timezone", new_callable=AsyncMock, return_value="UTC")
    async def test_claude_prompt_reports_shell_first_core_tool_summary(self, *mocks: MagicMock) -> None:
        from app.workflows._heartbeat_prompt import build_heartbeat_prompt

        prompt = await build_heartbeat_prompt(
            model_review_due=False,
            model_review_label="skip",
            provider="claude",
        )

        assert "none; shell-first core tools only" in prompt


class TestProtectionStatusSummary:
    """Tests for the heartbeat protection summary block."""

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_backup_schedule", new_callable=AsyncMock)
    @patch("app.workflows._heartbeat_data._fetch_backup_status", new_callable=AsyncMock)
    async def test_returns_target_project_backup_summary(
        self,
        mock_status: AsyncMock,
        mock_schedule: AsyncMock,
    ) -> None:
        mock_status.return_value = "LATEST bkp-123|completed|8.5MB"
        mock_schedule.return_value = "agent-hub            project    enabled  daily    30   Agent Hub"

        result = await _get_protection_status_summary("agent-hub")

        assert result.startswith("\n<protection_status>")
        assert "LATEST bkp-123|completed|8.5MB" in result
        assert "agent-hub            project    enabled  daily    30   Agent Hub" in result
        mock_status.assert_called_once_with("agent-hub")
        mock_schedule.assert_called_once_with("agent-hub")

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_backup_schedule", new_callable=AsyncMock)
    @patch("app.workflows._heartbeat_data._fetch_backup_status", new_callable=AsyncMock)
    async def test_empty_when_no_backup_data(
        self,
        mock_status: AsyncMock,
        mock_schedule: AsyncMock,
    ) -> None:
        mock_status.return_value = ""
        mock_schedule.return_value = ""

        assert await _get_protection_status_summary("agent-hub") == ""


class TestCleanupStatusSummary:
    """Tests for heartbeat cleanup-status section."""

    @pytest.mark.asyncio
    @patch(
        "app.workflows._heartbeat_data._fetch_cleanup_status_response",
        new_callable=AsyncMock,
        return_value={
            "compact": "CLEANUP[all]:repos=3 needs_cleanup=1 checkpoints=2 dirty=1 orphan=1 prunable=0",
            "payload": {"repositories": []},
        },
    )
    async def test_returns_xml_block(self, _mock_fetch: AsyncMock) -> None:
        result = await _get_cleanup_status_summary()
        assert result.startswith("\n<cleanup_status>")
        assert "needs_cleanup=1" in result
        assert result.endswith("</cleanup_status>")

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_cleanup_status_response", new_callable=AsyncMock, return_value=None)
    async def test_returns_empty_when_no_cleanup_state(self, _mock_fetch: AsyncMock) -> None:
        assert await _get_cleanup_status_summary() == ""

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_cleanup_status_response", new_callable=AsyncMock)
    async def test_filters_to_target_project(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = {
            "compact": (
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=1 dirty=1 orphan=0 prunable=0\n"
                "agent-hub checkpoints:1 dirty:1 orphan:0 prunable:0 tasks:task-2\n"
            ),
            "payload": {"repositories": []},
        }

        result = await _get_cleanup_status_summary("agent-hub")

        mock_fetch.assert_called_once_with("agent-hub")
        assert "agent-hub checkpoints:1 dirty:1" in result
        assert "summitflow" not in result

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_cleanup_status_response", new_callable=AsyncMock)
    async def test_builds_actionable_cleanup_from_structured_payload(
        self,
        mock_fetch_response: AsyncMock,
    ) -> None:
        mock_fetch_response.return_value = {
            "compact": (
                "CLEANUP[all]:repos=1 needs_cleanup=1 checkpoints=1 dirty=0 stale_cp=0 snap=0 orphan=1 prunable=0\n"
                "summitflow checkpoints:1 dirty:0 orphan:1 prunable:0 tasks:task-aa44180c"
            ),
            "payload": {
                "repositories": [
                    {
                        "project_id": "summitflow",
                        "needs_merge_tasks": ["task-aa44180c"],
                        "conflict_tasks": [],
                        "review_tasks": [],
                        "salvage_task_ids": [],
                        "review_orphan_task_ids": [],
                        "orphan_branch_names": ["task-ee55ff66/main"],
                    }
                ]
            },
        }

        result = await _get_cleanup_status_summary()

        assert "ACTIONABLE-CLEANUP[2]" in result
        assert "- summitflow | finalize | task-aa44180c" in result
        assert "- summitflow | orphan_branch | task-ee55ff66" in result

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_cleanup_status_response", new_callable=AsyncMock)
    async def test_omits_reconciled_workstream_items_from_actionable_cleanup(
        self,
        mock_fetch_response: AsyncMock,
    ) -> None:
        mock_fetch_response.return_value = {
            "compact": (
                "CLEANUP[all]:repos=1 needs_cleanup=1 checkpoints=2 dirty=0 stale_cp=0 snap=0 orphan=0 prunable=0\n"
                "summitflow checkpoints:2 dirty:0 orphan:0 prunable:0 tasks:task-aa44180c,task-bb22cc33 "
                "finalize:task-aa44180c review:task-bb22cc33"
            ),
            "payload": {
                "repositories": [
                    {
                        "project_id": "summitflow",
                        "needs_merge_tasks": ["task-aa44180c"],
                        "conflict_tasks": [],
                        "review_tasks": ["task-bb22cc33"],
                        "salvage_task_ids": [],
                        "review_orphan_task_ids": [],
                        "orphan_branch_names": [],
                    }
                ]
            },
        }

        result = await _get_cleanup_status_summary(
            workstream_rows=[
                {
                    "project_id": "summitflow",
                    "external_id": "task-aa44180c",
                    "current_branch": "task-aa44180c/main",
                    "status": "completed",
                    "workstream_status": "authoritative",
                },
                {
                    "project_id": "summitflow",
                    "external_id": "task-aa44180c",
                    "current_branch": "task-aa44180c/old",
                    "status": "completed",
                    "workstream_status": "superseded",
                },
            ]
        )

        assert "ACTIONABLE-CLEANUP[1]" in result
        assert "- summitflow | review | task-bb22cc33" in result
        assert "- summitflow | finalize | task-aa44180c" not in result

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_cleanup_status_response", new_callable=AsyncMock)
    async def test_reports_zero_actionable_cleanup_when_only_reconciled_residue_remains(
        self,
        mock_fetch_response: AsyncMock,
    ) -> None:
        mock_fetch_response.return_value = {
            "compact": (
                "CLEANUP[all]:repos=1 needs_cleanup=1 checkpoints=2 dirty=0 stale_cp=0 snap=0 orphan=0 prunable=0\n"
                "summitflow checkpoints:2 dirty:0 orphan:0 prunable:0 review:task-aa44180c"
            ),
            "payload": {
                "repositories": [
                    {
                        "project_id": "summitflow",
                        "needs_merge_tasks": [],
                        "conflict_tasks": [],
                        "review_tasks": ["task-aa44180c"],
                        "salvage_task_ids": [],
                        "review_orphan_task_ids": [],
                        "orphan_branch_names": [],
                    }
                ]
            },
        }

        result = await _get_cleanup_status_summary(
            workstream_rows=[
                {
                    "project_id": "summitflow",
                    "external_id": "task-aa44180c",
                    "current_branch": "task-aa44180c/main",
                    "status": "completed",
                    "workstream_status": "authoritative",
                },
                {
                    "project_id": "summitflow",
                    "external_id": "task-aa44180c",
                    "current_branch": "task-aa44180c/old",
                    "status": "completed",
                    "workstream_status": "superseded",
                },
            ]
        )

        assert "ACTIONABLE-CLEANUP[0]" in result
        assert "already reconciled authoritative/superseded" in result
        assert "- summitflow | review | task-aa44180c" not in result


class TestFetchCleanupStatus:
    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._read_project_api_url", return_value="http://localhost:8001/api")
    @patch("app.workflows._heartbeat_data.httpx.AsyncClient")
    async def test_returns_compact_cleanup_from_api(
        self,
        mock_client_cls: MagicMock,
        _mock_read_api_url: MagicMock,
    ) -> None:
        fake_client = _FakeAsyncClient(
            _FakeGitStatusResponse(
                {
                    "compact": (
                        "CLEANUP[all]:repos=2 needs_cleanup=1 checkpoints=1 dirty=0 stale_cp=0 snap=0 orphan=1 prunable=0\n"
                        "summitflow checkpoints:1 dirty:0 orphan:1 prunable:0 tasks:task-1"
                    )
                }
            )
        )
        mock_client_cls.return_value = fake_client

        result = await _fetch_cleanup_status()

        assert result == (
            "CLEANUP[all]:repos=2 needs_cleanup=1 checkpoints=1 dirty=0 stale_cp=0 snap=0 orphan=1 prunable=0\n"
            "summitflow checkpoints:1 dirty:0 orphan:1 prunable:0 tasks:task-1"
        )
        assert fake_client.requested_urls == ["http://localhost:8001/api/git/cleanup-status"]


class TestFetchTaskOverviewRaw:
    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._read_project_api_url", return_value="http://localhost:8001/api")
    @patch("app.workflows._heartbeat_data.httpx.AsyncClient")
    async def test_returns_ready_all_raw_from_api(
        self,
        mock_client_cls: MagicMock,
        _mock_read_api_url: MagicMock,
    ) -> None:
        fake_client = _FakeAsyncClient(
            _FakeGitStatusResponse(
                {
                    "raw": (
                        "READY-ALL[1 ready, 0 blocked, 1 active, 1 stale across 1 projects]\n\n"
                        "agent-hub (1 ready, 1 active, 1 stale)\n"
                        "  ~ task-live P2 task     [M] Live task [running]\n"
                        "  ? task-stale P2 task     [M] Stale task [stale-running]\n"
                        "    task-ready P1 bug      [A] Ready fix\n"
                    )
                }
            )
        )
        mock_client_cls.return_value = fake_client

        result = await _fetch_task_overview_raw()

        assert "READY-ALL[1 ready, 0 blocked, 1 active, 1 stale across 1 projects]" in result
        assert "~ task-live" in result
        assert "? task-stale" in result
        assert fake_client.requested_urls == ["http://localhost:8001/api/tasks/ready-all"]


class TestActiveSpecialistInventory:
    """Tests for active specialist inventory in heartbeat prompt context."""

    @pytest.mark.asyncio
    async def test_groups_active_non_owner_specialists_by_project_and_agent(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-1",
                "agent_slug": "reviewer",
                "project_id": "summitflow",
                "parent_session_id": "parent-1",
                "request_source": "dispatch",
                "age_minutes": 4,
            },
            {
                "session_id": "sess-2",
                "agent_slug": "reviewer",
                "project_id": "summitflow",
                "parent_session_id": "parent-2",
                "request_source": "dispatch",
                "age_minutes": 1,
            },
            {
                "session_id": "sess-3",
                "agent_slug": "investment-committee",
                "project_id": "portfolio-ai",
                "parent_session_id": None,
                "request_source": "dispatch",
                "age_minutes": 2,
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_active_specialist_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_active_specialist_inventory()

        assert "<active_specialist_inventory>" in result
        assert "summitflow | reviewer | active=2" in result
        assert "next=dedupe_or_wait" in result
        assert "portfolio-ai | investment-committee | active=1" in result
        assert "next=wait_or_complement" in result

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_active_specialists_exist(self) -> None:
        with patch(
            "app.workflows._heartbeat_data._query_active_specialist_sessions",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await _get_active_specialist_inventory()

        assert result == ""

    @pytest.mark.asyncio
    async def test_passes_target_project_filter(self) -> None:
        with patch(
            "app.workflows._heartbeat_data._query_active_specialist_sessions",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_query:
            await _get_active_specialist_inventory("agent-hub")

        mock_query.assert_awaited_once_with("agent-hub")

    @pytest.mark.asyncio
    async def test_query_excludes_dead_candidate_specialists(self) -> None:
        now = datetime.now(UTC)
        session_factory, _mock_db = _mock_async_session_with_scalars(
            [
                MagicMock(
                    id="sess-persona",
                    agent_slug="persona",
                    project_id="agent-hub",
                    parent_session_id=None,
                    request_source="heartbeat",
                    created_at=now,
                    updated_at=now,
                    status="active",
                    external_id=None,
                    current_branch=None,
                    provider_metadata={
                        "live_activity": {
                            "phase": "waiting_for_model",
                            "status": "active",
                            "summary": "Heartbeat running",
                            "last_event_type": "heartbeat",
                            "last_event_at": now.isoformat(),
                            "last_model_activity_at": now.isoformat(),
                            "outstanding_tool_calls": 0,
                            "tool_calls_count": 1,
                        }
                    },
                ),
                MagicMock(
                    id="sess-live",
                    agent_slug="reviewer",
                    project_id="agent-hub",
                    parent_session_id="parent-live",
                    request_source="dispatch",
                    created_at=now,
                    updated_at=now,
                    status="active",
                    external_id=None,
                    current_branch=None,
                    provider_metadata={
                        "live_activity": {
                            "phase": "waiting_for_model",
                            "status": "active",
                            "summary": "Waiting for model after Read",
                            "last_event_type": "tool_result",
                            "last_event_at": (now - timedelta(minutes=2)).isoformat(),
                            "last_model_activity_at": (now - timedelta(minutes=2)).isoformat(),
                            "outstanding_tool_calls": 0,
                            "tool_calls_count": 1,
                        }
                    },
                ),
                MagicMock(
                    id="sess-dead",
                    agent_slug="reviewer",
                    project_id="agent-hub",
                    parent_session_id="parent-dead",
                    request_source="dispatch",
                    created_at=now - timedelta(minutes=45),
                    updated_at=now - timedelta(minutes=45),
                    status="active",
                    external_id=None,
                    current_branch=None,
                    provider_metadata={
                        "live_activity": {
                            "phase": "waiting_for_model",
                            "status": "active",
                            "summary": "Transcript sync heartbeat",
                            "last_event_type": "heartbeat",
                            "last_event_at": (now - timedelta(minutes=45)).isoformat(),
                            "last_model_activity_at": (now - timedelta(hours=2)).isoformat(),
                            "last_heartbeat_at": now.isoformat(),
                            "outstanding_tool_calls": 0,
                            "tool_calls_count": 2,
                        }
                    },
                ),
            ]
        )

        with patch("app.db.async_session", session_factory):
            result = await _query_active_specialist_sessions("agent-hub", now=now)

        assert [row["session_id"] for row in result] == ["sess-live"]


class TestActiveSessionInventory:
    """Tests for active session inventory in heartbeat prompt context."""

    @pytest.mark.asyncio
    async def test_query_excludes_dead_candidate_sessions(self) -> None:
        now = datetime.now(UTC)
        live_session = MagicMock(
            id="sess-live",
            agent_slug="coder",
            external_id="task-live",
            current_branch=None,
            health_detail="executing_tool:Bash",
            last_activity_at=now - timedelta(minutes=2),
            created_at=now - timedelta(minutes=10),
            status="active",
            provider_metadata={
                "live_activity": {
                    "phase": "waiting_for_model",
                    "status": "active",
                    "summary": "Waiting after tool result",
                    "last_event_type": "tool_result",
                    "last_event_at": (now - timedelta(minutes=2)).isoformat(),
                    "last_model_activity_at": (now - timedelta(minutes=2)).isoformat(),
                    "outstanding_tool_calls": 0,
                    "tool_calls_count": 4,
                }
            },
        )
        dead_session = MagicMock(
            id="sess-dead",
            agent_slug="coder",
            external_id="task-dead",
            current_branch=None,
            health_detail="waiting_for_model",
            last_activity_at=now - timedelta(minutes=45),
            created_at=now - timedelta(minutes=55),
            status="active",
            provider_metadata={
                "live_activity": {
                    "phase": "waiting_for_model",
                    "status": "active",
                    "summary": "Transcript sync heartbeat",
                    "last_event_type": "heartbeat",
                    "last_event_at": (now - timedelta(minutes=45)).isoformat(),
                    "last_model_activity_at": (now - timedelta(minutes=45)).isoformat(),
                    "last_heartbeat_at": now.isoformat(),
                    "outstanding_tool_calls": 0,
                    "tool_calls_count": 2,
                }
            },
        )
        session_factory, _mock_db = _mock_async_session_with_rows(
            [
                (live_session, True, 7),
                (dead_session, True, 2),
            ]
        )

        with patch("app.db.async_session", session_factory):
            result = await _query_active_sessions_for_heartbeat("agent-hub", now=now)

        assert [row["task_ref"] for row in result] == ["task-live"]


class TestRecentlyCompletedSessionsSection:
    """Tests for recently completed session summaries in heartbeat context."""

    @pytest.mark.asyncio
    async def test_excludes_persona_sessions_from_completed_summary(self) -> None:
        now = datetime.now(UTC)
        session_factory, mock_db = _mock_async_session_with_rows(
            [
                MagicMock(
                    id="sess-1",
                    agent_slug="refactor",
                    project_id="agent-hub",
                    summary_oneliner="Refactored the tool handler",
                    created_at=now,
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.fetch_session_display_summary_results",
                new_callable=AsyncMock,
                return_value={
                    "sess-1": MagicMock(
                        summary="Refactored the tool handler and verified follow-up.",
                        has_summary_tag=True,
                        summary_outcome="completed",
                        has_unresolved_blocker=False,
                    )
                },
            ),
        ):
            result = await _fetch_recently_completed_sessions_section()

        executed_query = str(mock_db.execute.await_args.args[0])
        assert "Recently completed sessions: 1" in result
        assert "refactor on agent-hub" in result
        assert "Refactored the tool handler and verified follow-up." in result
        assert "persona" not in result
        assert "sessions.agent_slug != :agent_slug_1" in executed_query

    @pytest.mark.asyncio
    async def test_skips_sessions_without_clean_display_summary(self) -> None:
        now = datetime.now(UTC)
        session_factory, _mock_db = _mock_async_session_with_rows(
            [
                MagicMock(
                    id="sess-noisy",
                    agent_slug="coder",
                    project_id="agent-hub",
                    summary_oneliner="Noisy fallback summary",
                    created_at=now,
                ),
                MagicMock(
                    id="sess-clean",
                    agent_slug="refactor",
                    project_id="summitflow",
                    summary_oneliner="Refactored cleanup flow",
                    created_at=now,
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.fetch_session_display_summary_results",
                new_callable=AsyncMock,
                return_value={
                    "sess-noisy": MagicMock(summary=None, has_summary_tag=False),
                    "sess-clean": MagicMock(
                        summary="Refactored cleanup flow and verified the lane state.",
                        has_summary_tag=True,
                        summary_outcome="completed",
                        has_unresolved_blocker=False,
                    ),
                },
            ),
        ):
            result = await _fetch_recently_completed_sessions_section()

        assert "Recently completed sessions: 1" in result
        assert "sess-noisy" not in result
        assert "summitflow" in result
        assert "Refactored cleanup flow and verified the lane state." in result

    @pytest.mark.asyncio
    async def test_skips_sessions_without_explicit_summary_tag(self) -> None:
        now = datetime.now(UTC)
        session_factory, _mock_db = _mock_async_session_with_rows(
            [
                MagicMock(
                    id="sess-fallback",
                    agent_slug="coder",
                    project_id="agent-hub",
                    summary_oneliner="Fallback summary",
                    created_at=now,
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.fetch_session_display_summary_results",
                new_callable=AsyncMock,
                return_value={
                    "sess-fallback": MagicMock(
                        summary="Fallback summary cleaned from prose.",
                        has_summary_tag=False,
                        summary_outcome=None,
                        has_unresolved_blocker=False,
                    )
                },
            ),
        ):
            result = await _fetch_recently_completed_sessions_section()

        assert result == ""

    @pytest.mark.asyncio
    async def test_skips_completed_summary_that_still_describes_blocker(self) -> None:
        now = datetime.now(UTC)
        session_factory, _mock_db = _mock_async_session_with_rows(
            [
                MagicMock(
                    id="sess-blocked",
                    agent_slug="coder",
                    project_id="agent-hub",
                    summary_oneliner="Publish is blocked.",
                    created_at=now,
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.fetch_session_display_summary_results",
                new_callable=AsyncMock,
                return_value={
                    "sess-blocked": MagicMock(
                        summary="Publish is blocked because detached rebuild is unavailable.",
                        has_summary_tag=True,
                        summary_outcome="completed",
                        has_unresolved_blocker=True,
                    )
                },
            ),
        ):
            result = await _fetch_recently_completed_sessions_section()

        assert result == ""

    @pytest.mark.asyncio
    async def test_skips_benchmark_sessions_from_completed_summary(self) -> None:
        now = datetime.now(UTC)
        session_factory, _mock_db = _mock_async_session_with_rows(
            [
                MagicMock(
                    id="sess-benchmark",
                    agent_slug="coder",
                    project_id="agent-hub",
                    external_id="benchmark:coder:1:abc12345",
                    summary_oneliner="Printed BRANCH_OK via bash",
                    created_at=now,
                ),
                MagicMock(
                    id="sess-real",
                    agent_slug="debugger",
                    project_id="summitflow",
                    external_id="task-d2754718",
                    summary_oneliner="Reconciled the stale lane and verified runtime truth.",
                    created_at=now,
                ),
            ]
        )

        with (
            patch("app.db.async_session", session_factory),
            patch(
                "app.workflows._heartbeat_data.fetch_session_display_summary_results",
                new_callable=AsyncMock,
                return_value={
                    "sess-benchmark": MagicMock(
                        summary="Printed BRANCH_OK via bash",
                        has_summary_tag=True,
                        summary_outcome="completed",
                        has_unresolved_blocker=False,
                    ),
                    "sess-real": MagicMock(
                        summary="Reconciled the stale lane and verified runtime truth.",
                        has_summary_tag=True,
                        summary_outcome="completed",
                        has_unresolved_blocker=False,
                    ),
                },
            ),
        ):
            result = await _fetch_recently_completed_sessions_section()

        assert "Recently completed sessions: 1" in result
        assert "Printed BRANCH_OK" not in result
        assert "debugger on summitflow" in result
        assert "Reconciled the stale lane and verified runtime truth." in result


class TestActiveWorkSummary:
    """Tests for active_work shaping in heartbeat context."""

    @pytest.mark.asyncio
    async def test_suppresses_completed_sessions_when_ready_work_exists_and_queue_is_clean(self) -> None:
        fake_overview = """READY-ALL[2 ready, 0 blocked, 0 active, 0 stale across 1 projects]

agent-hub (2 ready)
    task-52831804 P3 refactor [A] Refactor: backend/app/services/tools/_executor_consultation.py
    task-0e20ca4d P3 refactor [A] Refactor: backend/app/services/memory/session_analysis.py
"""

        with (
            patch(
                "app.workflows._heartbeat_data._fetch_task_overview",
                return_value=fake_overview,
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_active_sessions_section",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_recently_completed_sessions_section",
                new_callable=AsyncMock,
                return_value="Recently completed sessions: 1\n- refactor on agent-hub: old summary",
            ) as mock_completed,
        ):
            result = await _get_active_work_summary()

        assert "task-52831804" in result
        assert "Recently completed sessions" not in result
        mock_completed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_keeps_completed_sessions_when_live_or_stale_work_exists(self) -> None:
        fake_overview = """READY-ALL[1 ready, 0 blocked, 0 active, 1 stale across 1 projects]

agent-hub (1 ready, 1 stale)
  ? task-de53b498 P1 task     [M] Fix stale running queue state [stale-running]
    task-52831804 P3 refactor [A] Refactor: backend/app/services/tools/_executor_consultation.py
"""

        with (
            patch(
                "app.workflows._heartbeat_data._fetch_task_overview",
                return_value=fake_overview,
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_active_sessions_section",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_recently_completed_sessions_section",
                new_callable=AsyncMock,
                return_value="Recently completed sessions: 1\n- refactor on agent-hub: old summary",
            ) as mock_completed,
        ):
            result = await _get_active_work_summary()

        assert "Recently completed sessions: 1" in result
        mock_completed.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_recently_completed_sessions_section", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_data._fetch_active_sessions_section", new_callable=AsyncMock, return_value="")
    async def test_filters_task_overview_to_target_project(
        self,
        _mock_sessions: AsyncMock,
        _mock_completed: AsyncMock,
    ) -> None:
        task_overview = (
            "READY-ALL[2 ready, 0 blocked, 2 active, 0 stale across 2 projects]\n\n"
            "PROJECTS[2]\n"
            "- agent-hub | 1 ready, 1 active\n"
            "- summitflow | 1 ready, 1 active\n\n"
            "ACTIONABLE-READY[2]\n"
            "- agent-hub | task-1 | P2 refactor [A] | Refactor: backend/app/foo.py\n"
            "- summitflow | task-2 | P2 refactor [A] | Refactor: backend/app/bar.py\n"
        )

        result = await _get_active_work_summary(
            task_overview=task_overview,
            target_project_id="agent-hub",
        )

        assert "- agent-hub | 1 ready, 1 active" in result
        assert "- agent-hub | task-1" in result
        assert "summitflow" not in result

    @pytest.mark.asyncio
    @patch("app.workflows._heartbeat_data._fetch_recently_completed_sessions_section", new_callable=AsyncMock, return_value="")
    @patch("app.workflows._heartbeat_data._fetch_active_sessions_section", new_callable=AsyncMock, return_value="")
    async def test_builds_active_work_from_structured_payload(
        self,
        _mock_sessions: AsyncMock,
        _mock_completed: AsyncMock,
    ) -> None:
        task_overview_payload = {
            "summary": {"ready": 1, "blocked": 0, "active": 0, "stale": 0, "projects": 1},
            "projects": [
                {
                    "project_id": "agent-hub",
                    "ready_count": 1,
                    "blocked_count": 0,
                    "active_count": 0,
                    "stale_count": 0,
                    "ready_tasks": [
                        {
                            "id": "task-1",
                            "priority": 2,
                            "task_type": "refactor",
                            "execution_mode": "autonomous",
                            "title": "Refactor: backend/app/foo.py",
                        }
                    ],
                    "blocked_tasks": [],
                    "active_tasks": [],
                    "stale_tasks": [],
                }
            ],
        }

        result = await _get_active_work_summary(task_overview_payload=task_overview_payload)

        assert "READY-ALL[1 ready, 0 blocked, 0 active, 0 stale across 1 projects]" in result
        assert "PROJECTS[1]" in result
        assert "- agent-hub | task-1 | P2 refactor [A] | Refactor: backend/app/foo.py" in result


class TestGetWorkstreamInventory:
    """Tests for first-class workstream inventory classification."""

    @pytest.mark.asyncio
    async def test_reports_completed_lane_ready_for_closure(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-1",
                "agent_slug": "coder",
                "project_id": "summitflow",
                "external_id": "task-123",
                "current_branch": "task-123/main",
                "status": "completed",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ), patch(
            "app.workflows._heartbeat_data._fetch_task_overview_raw",
            return_value="agent-hub (1)\n  * task-123 pending Refactor",
        ):
            result = await _get_workstream_inventory()

        assert "<workstream_inventory>" in result
        assert "task-123" in result
        assert "state=completed_ready_for_closure" in result
        assert (
            'bash: st context task-123 then st done task-123 --admin --message '
            '"Completed work verified; task closed."'
            in result
        )

    @pytest.mark.asyncio
    async def test_reports_shell_first_workstream_actions_for_claude(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-1",
                "agent_slug": "coder",
                "project_id": "summitflow",
                "external_id": "task-123",
                "current_branch": "task-123/main",
                "status": "completed",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ), patch(
            "app.workflows._heartbeat_data._fetch_task_overview_raw",
            return_value="agent-hub (1)\n  * task-123 pending Refactor",
        ):
            result = await _get_workstream_inventory(provider="claude")

        assert (
            'bash: st context task-123 then st done task-123 --admin --message '
            '"Completed work verified; task closed."'
            in result
        )

    @pytest.mark.asyncio
    async def test_branch_only_completed_lane_still_recovers_task_id(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-branch-only",
                "agent_slug": "refactor",
                "project_id": "a-term",
                "external_id": None,
                "current_branch": "task-a3903361/main",
                "status": "completed",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ), patch(
            "app.workflows._heartbeat_data._fetch_task_overview_raw",
            return_value="a-term (1)\n  * task-a3903361 pending Refactor",
        ):
            result = await _get_workstream_inventory()

        assert "task-a3903361" in result
        assert "state=completed_ready_for_closure" in result
        assert (
            'bash: st context task-a3903361 then st done task-a3903361 --admin --message '
            '"Completed work verified; task closed."'
            in result
        )

    @pytest.mark.asyncio
    async def test_reports_stale_active_lane(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-2",
                "agent_slug": "reviewer",
                "project_id": "agent-hub",
                "external_id": "task-999",
                "current_branch": "task-999/main",
                "status": "active",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 480,
                "idle_minutes": 480,
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_workstream_inventory()

        assert "task-999" in result
        assert "state=stale_active" in result
        assert "st session-events -T task-999 --page-size 100" in result

    @pytest.mark.asyncio
    async def test_omits_completed_lane_when_task_is_not_in_current_queue_snapshot(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-gone",
                "agent_slug": "refactor",
                "project_id": "agent-hub",
                "external_id": "task-deadbeef",
                "current_branch": "task-deadbeef/main",
                "status": "completed",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 30,
                "idle_minutes": 30,
            },
        ]

        with (
            patch(
                "app.workflows._heartbeat_data._query_recent_workstream_sessions",
                new_callable=AsyncMock,
                return_value=fake_rows,
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_task_overview_raw",
                return_value="READY-ALL[0 ready, 0 blocked, 0 active, 0 stale across 0 projects]",
            ),
        ):
            result = await _get_workstream_inventory()

        assert result == ""

    @pytest.mark.asyncio
    async def test_omits_retired_lane_when_task_is_visible_in_current_queue_snapshot(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-retired",
                "agent_slug": "refactor",
                "project_id": "agent-hub",
                "external_id": "task-d24e47d8",
                "current_branch": "task-d24e47d8/main",
                "status": "completed",
                "workstream_status": "retired",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 30,
                "idle_minutes": 30,
            },
        ]

        with (
            patch(
                "app.workflows._heartbeat_data._query_recent_workstream_sessions",
                new_callable=AsyncMock,
                return_value=fake_rows,
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_task_overview_raw",
                return_value=(
                    "READY-ALL[1 ready, 0 blocked, 0 active, 0 stale across 1 projects]\n\n"
                    "agent-hub (1 ready, 0 active)\n"
                    "  * task-d24e47d8 P2 refactor [A] Refactor session ingestion"
                ),
            ),
        ):
            result = await _get_workstream_inventory()

        assert result == ""

    @pytest.mark.asyncio
    async def test_omits_completed_lanes_without_task_ids(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-coder",
                "agent_slug": "coder",
                "project_id": "agent-hub",
                "external_id": None,
                "current_branch": "branch-ok",
                "status": "completed",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with (
            patch(
                "app.workflows._heartbeat_data._query_recent_workstream_sessions",
                new_callable=AsyncMock,
                return_value=fake_rows,
            ),
            patch(
                "app.workflows._heartbeat_data._fetch_task_overview_raw",
                return_value="READY-ALL[0 ready, 0 blocked, 0 active, 0 stale across 0 projects]",
            ),
        ):
            result = await _get_workstream_inventory()

        assert result == ""

    @pytest.mark.asyncio
    async def test_reports_stale_active_lane_from_idle_time_not_session_age(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-2",
                "agent_slug": "refactor",
                "project_id": "agent-hub",
                "external_id": "task-123",
                "current_branch": "task-123/main",
                "status": "active",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 6,
                "idle_minutes": 12,
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_workstream_inventory()

        assert "task-123" in result
        assert "state=stale_active" in result
        assert "idle=12m" in result

    @pytest.mark.asyncio
    async def test_reports_mixed_lane_when_multiple_branches_active(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-3",
                "agent_slug": "coder",
                "project_id": "summitflow",
                "external_id": "task-777",
                "current_branch": "task-777/main",
                "working_dir": "/tmp/lanes/task-777-main",
                "status": "active",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 10,
            },
            {
                "session_id": "sess-4",
                "agent_slug": "debugger",
                "project_id": "summitflow",
                "external_id": "task-777",
                "current_branch": "task-777/follow-up",
                "working_dir": "/tmp/lanes/task-777-follow-up",
                "status": "active",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 5,
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_workstream_inventory()

        assert "task-777" in result
        assert "state=mixed" in result
        assert "branches=2" in result
        assert "checkout=/tmp/lanes/task-777-follow-up" in result or "checkout=/tmp/lanes/task-777-main" in result

    @pytest.mark.asyncio
    async def test_reports_working_dir_when_lane_has_working_dir(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-7",
                "agent_slug": "refactor",
                "project_id": "a-term",
                "external_id": "task-999",
                "current_branch": "task-999/main",
                "working_dir": "/home/testuser//.local/share/st/checkpoints/a-term/task-999",
                "status": "active",
                "created_at": "ignored",
                "updated_at": "ignored",
                "age_minutes": 2,
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_workstream_inventory()

        assert "task-999" in result
        assert "checkout=/home/testuser//.local/share/st/checkpoints/a-term/task-999" in result

    @pytest.mark.asyncio
    async def test_reports_reconciled_lane_from_persisted_lifecycle_markers(self) -> None:
        fake_rows = [
            {
                "session_id": "sess-5",
                "agent_slug": "coder",
                "project_id": "summitflow",
                "external_id": "task-888",
                "current_branch": "task-888/main",
                "status": "completed",
                "workstream_status": "authoritative",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
            {
                "session_id": "sess-6",
                "agent_slug": "reviewer",
                "project_id": "summitflow",
                "external_id": "task-888",
                "current_branch": "task-888/old",
                "status": "completed",
                "workstream_status": "superseded",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ):
            result = await _get_workstream_inventory()

        assert "task-888" in result
        assert "state=reconciled" in result
        assert "lifecycle=authoritative,superseded" in result

    @pytest.mark.asyncio
    async def test_promotes_stale_running_ready_all_entries_into_workstream_inventory(self) -> None:
        fake_overview = """READY-ALL[1 ready, 0 blocked, 0 active, 1 stale across 1 projects]

agent-hub (1 ready, 1 stale)
  ? task-de53b498 P1 task     [M] Add persona heartbeat provider regression tests for ... [stale-running]
"""

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.workflows._heartbeat_data._fetch_task_overview_raw",
            return_value=fake_overview,
        ):
            result = await _get_workstream_inventory()

        assert "task-de53b498" in result
        assert "state=stale_running_task" in result
        assert (
            "st session-events -T task-de53b498 --page-size 100; "
            "reconcile stale task state only after verification"
            in result
        )

    @pytest.mark.asyncio
    async def test_promotes_stale_running_entries_from_task_overview_payload(self) -> None:
        task_overview_payload = {
            "summary": {"ready": 1, "blocked": 0, "active": 0, "stale": 1, "projects": 1},
            "projects": [
                {
                    "project_id": "agent-hub",
                    "ready_count": 1,
                    "blocked_count": 0,
                    "active_count": 0,
                    "stale_count": 1,
                    "ready_tasks": [
                        {
                            "id": "task-ready001",
                            "priority": 2,
                            "task_type": "refactor",
                            "execution_mode": "autonomous",
                            "title": "Refactor: backend/app/foo.py",
                        }
                    ],
                    "blocked_tasks": [],
                    "active_tasks": [],
                    "stale_tasks": [
                        {
                            "id": "task-de53b498",
                            "priority": 1,
                            "task_type": "task",
                            "execution_mode": "manual",
                            "title": "Add persona heartbeat provider regression tests for ...",
                        }
                    ],
                }
            ],
        }

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await _get_workstream_inventory(task_overview_payload=task_overview_payload)

        assert "task-de53b498" in result
        assert "state=stale_running_task" in result

    @pytest.mark.asyncio
    async def test_stale_running_queue_truth_overrides_historical_session_rows(self) -> None:
        fake_overview = """READY-ALL[1 ready, 0 blocked, 0 active, 1 stale across 1 projects]

agent-hub (1 ready, 1 stale)
  ? task-de53b498 P1 task     [M] Add persona heartbeat provider regression tests for ... [stale-running]
"""
        fake_rows = [
            {
                "session_id": "sess-1",
                "agent_slug": "refactor",
                "project_id": "agent-hub",
                "external_id": "task-de53b498",
                "current_branch": "task-de53b498/main",
                "status": "completed",
                "workstream_status": "superseded",
                "created_at": "ignored",
                "updated_at": "ignored",
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new_callable=AsyncMock,
            return_value=fake_rows,
        ), patch(
            "app.workflows._heartbeat_data._fetch_task_overview_raw",
            return_value=fake_overview,
        ):
            result = await _get_workstream_inventory()

        assert "task-de53b498" in result
        assert "state=stale_running_task" in result
        assert "state=superseded" not in result


class TestWorkstreamLaneContract:
    """Tests for lane classification precedence and automation boundaries."""

    def test_classify_reconciled_wins_over_completed_ready_for_closure(self) -> None:
        rows = [
            {
                "status": "completed",
                "workstream_status": "authoritative",
                "current_branch": "task-1/main",
            },
            {
                "status": "completed",
                "workstream_status": "superseded",
                "current_branch": "task-1/old",
            },
        ]

        assert _classify_workstream_lane(rows) == "reconciled"

    def test_classify_retired_wins_over_completed_ready_for_closure(self) -> None:
        rows = [
            {
                "status": "completed",
                "workstream_status": "retired",
                "current_branch": "task-2/main",
            }
        ]

        assert _classify_workstream_lane(rows) == "retired"

    def test_classify_superseded_wins_over_completed_ready_for_closure(self) -> None:
        rows = [
            {
                "status": "completed",
                "workstream_status": "superseded",
                "current_branch": "task-3/main",
            }
        ]

        assert _classify_workstream_lane(rows) == "superseded"

    def test_classify_active_wins_when_lane_is_fresh(self) -> None:
        rows = [
            {
                "status": "active",
                "current_branch": "task-4/main",
                "age_minutes": 15,
                "idle_minutes": 5,
            }
        ]

        assert _classify_workstream_lane(rows) == "active"

    def test_classify_orphaned_when_lane_has_no_active_or_completed_status(self) -> None:
        rows = [
            {
                "status": "paused",
                "current_branch": "task-5/main",
            }
        ]

        assert _classify_workstream_lane(rows) == "orphaned"

    def test_build_next_action_limits_automation_for_informational_states(self) -> None:
        assert (
            _build_workstream_next_action(
                state="mixed",
                project_id="summitflow",
                task_id="task-6",
            )
            == "split/promotion cleanup; do not dispatch more implementation onto this lane"
        )
        assert (
            _build_workstream_next_action(
                state="reconciled",
                project_id="summitflow",
                task_id="task-6",
            )
            == "authoritative lane recorded; avoid redispatch unless new facts contradict it"
        )
        assert (
            _build_workstream_next_action(
                state="retired",
                project_id="summitflow",
                task_id="task-6",
            )
            == "retired_lane_no_action"
        )
        assert (
            _build_workstream_next_action(
                state="superseded",
                project_id="summitflow",
                task_id="task-6",
            )
            == "superseded_lane_no_action"
        )

    def test_build_next_action_uses_shell_first_guidance(self) -> None:
        assert (
            _build_workstream_next_action(
                state="completed_ready_for_closure",
                project_id="agent-hub",
                task_id="task-6",
                provider="claude",
            )
            == 'bash: st context task-6 then st done task-6 --admin --message "Completed work verified; task closed."'
        )
