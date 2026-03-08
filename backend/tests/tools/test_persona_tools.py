"""Tests for persona-related tool implementations in executor sub-modules."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.persona import Persona


def _make_persona(**overrides) -> MagicMock:
    """Create a mock Persona with sensible defaults."""
    defaults = {
        "id": 1,
        "agent_id": 10,
        "name": "Jenny",
        "personality": "I'm a helpful assistant.",
        "heartbeat_instructions": None,
        "user_context": "User prefers concise answers.",
        "voice_id": "en-US-AriaNeural",
        "voice_enabled": False,
        "heartbeat_interval_minutes": 60,
        "avatar_url": None,
        "greeting": None,
        "onboarding_complete": True,
        "onboarding_phase": "complete",
        "session_reset_mode": "off",
        "session_reset_hour": 9,
        "session_reset_idle_minutes": 120,
        "limits": None,
        "version": 2,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Persona)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _mock_async_session(persona):
    """Create a mock async_session context manager that returns a mock db."""
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = persona
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session, mock_db


class TestReadPersonality:
    """Tests for read_personality tool."""

    @pytest.mark.asyncio
    async def test_returns_personality_text(self):
        from app.services.tools._executor_persona import read_personality

        persona = _make_persona(personality="I'm creative and bold.")
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await read_personality()

        assert result == "I'm creative and bold."

    @pytest.mark.asyncio
    async def test_returns_placeholder_when_empty(self):
        from app.services.tools._executor_persona import read_personality

        persona = _make_persona(personality=None)
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await read_personality()

        assert "No personality document set" in result


class TestWritePersonality:
    """Tests for write_personality tool."""

    @pytest.mark.asyncio
    async def test_updates_personality_and_version(self):
        from app.services.tools._executor_persona import write_personality

        persona = _make_persona(version=3)
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await write_personality("New personality.", "Testing")

        assert "Personality updated" in result
        assert "version 4" in result
        assert persona.personality == "New personality."
        assert persona.version == 4


class TestWriteUserContext:
    """Tests for write_user_context tool."""

    @pytest.mark.asyncio
    async def test_updates_user_context(self):
        from app.services.tools._executor_persona import write_user_context

        persona = _make_persona(version=2)
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await write_user_context("Prefers morning standups.")

        assert "User context updated" in result
        assert persona.user_context == "Prefers morning standups."
        assert persona.version == 3


class TestReadUserContext:
    """Tests for read_user_context tool."""

    @pytest.mark.asyncio
    async def test_returns_context_text(self):
        from app.services.tools._executor_persona import read_user_context

        persona = _make_persona(user_context="Likes verbose output.")
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await read_user_context()

        assert result == "Likes verbose output."

    @pytest.mark.asyncio
    async def test_returns_placeholder_when_empty(self):
        from app.services.tools._executor_persona import read_user_context

        persona = _make_persona(user_context=None)
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await read_user_context()

        assert "No user context set" in result


class TestMarkMemoryRelevant:
    """Tests for mark_memory_relevant tool."""

    @pytest.mark.asyncio
    async def test_adds_tag(self):
        from app.services.tools._executor_persona import mark_memory_relevant

        with (
            patch(
                "app.services.memory.episode_property_queries.get_episode_tags",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.memory.episode_property_setters.set_episode_tags",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_set,
        ):
            result = await mark_memory_relevant("abc12345-uuid")

        assert "marked as persona-relevant" in result
        mock_set.assert_awaited_once_with("abc12345-uuid", ["persona-relevant"])

    @pytest.mark.asyncio
    async def test_idempotent_when_already_tagged(self):
        from app.services.tools._executor_persona import mark_memory_relevant

        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            return_value=["persona-relevant"],
        ):
            result = await mark_memory_relevant("abc12345-uuid")

        assert "already tagged" in result

    @pytest.mark.asyncio
    async def test_error_handling(self):
        from app.services.tools._executor_persona import mark_memory_relevant

        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            side_effect=Exception("Database error"),
        ):
            result = await mark_memory_relevant("bad-uuid")

        assert "Error" in result


class TestMarkMemoryIrrelevant:
    """Tests for mark_memory_irrelevant tool."""

    @pytest.mark.asyncio
    async def test_removes_tag(self):
        from app.services.tools._executor_persona import mark_memory_irrelevant

        with (
            patch(
                "app.services.memory.episode_property_queries.get_episode_tags",
                new_callable=AsyncMock,
                return_value=["persona-relevant", "other-tag"],
            ),
            patch(
                "app.services.memory.episode_property_setters.set_episode_tags",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_set,
        ):
            result = await mark_memory_irrelevant("abc12345-uuid")

        assert "Removed persona-relevant" in result
        mock_set.assert_awaited_once_with("abc12345-uuid", ["other-tag"])

    @pytest.mark.asyncio
    async def test_idempotent_when_not_tagged(self):
        from app.services.tools._executor_persona import mark_memory_irrelevant

        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            return_value=["other-tag"],
        ):
            result = await mark_memory_irrelevant("abc12345-uuid")

        assert "not tagged as persona-relevant" in result

    @pytest.mark.asyncio
    async def test_error_handling(self):
        from app.services.tools._executor_persona import mark_memory_irrelevant

        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            side_effect=Exception("Connection lost"),
        ):
            result = await mark_memory_irrelevant("bad-uuid")

        assert "Error" in result


class TestSubmitOnboarding:
    """Tests for submit_onboarding tool."""

    @pytest.mark.asyncio
    async def test_approved_returns_confirmation(self):
        from app.services.tools._executor_persona import submit_onboarding

        persona = _make_persona(
            onboarding_phase="in_progress",
            onboarding_complete=False,
            user_context="Some context.",
        )
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
            patch(
                "app.services.persona_service.submit_and_review_onboarding",
                new_callable=AsyncMock,
                return_value={"status": "approved", "feedback": "All good."},
            ),
        ):
            result = await submit_onboarding("Full onboarding summary")

        assert "APPROVED" in result
        assert "All good." in result

    @pytest.mark.asyncio
    async def test_rejected_returns_feedback(self):
        from app.services.tools._executor_persona import submit_onboarding

        persona = _make_persona(
            onboarding_phase="in_progress",
            onboarding_complete=False,
            user_context="Partial context.",
        )
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
            patch(
                "app.services.persona_service.submit_and_review_onboarding",
                new_callable=AsyncMock,
                return_value={"status": "rejected", "feedback": "Missing schedule."},
            ),
        ):
            result = await submit_onboarding("Partial summary")

        assert "REJECTED" in result
        assert "Missing schedule." in result

    @pytest.mark.asyncio
    async def test_error_handling(self):
        from app.services.tools._executor_persona import submit_onboarding

        persona = _make_persona()
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                side_effect=Exception("DB down"),
            ),
        ):
            result = await submit_onboarding("Summary")

        assert "Error" in result


class TestSendPush:
    """Tests for send_push tool."""

    @pytest.mark.asyncio
    async def test_sends_notification(self):
        from app.services.tools._executor_io import send_push

        mock_db = AsyncMock()

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.services.push_service.send_push",
                new_callable=AsyncMock,
                return_value=3,
            ),
        ):
            result = await send_push(
                title="Alert",
                body="Something happened",
                url="https://example.com",
                severity="warning",
                tag="test-tag",
            )

        assert "3 device(s)" in result
        assert "Alert" in result

    @pytest.mark.asyncio
    async def test_sends_with_minimal_params(self):
        from app.services.tools._executor_io import send_push

        mock_db = AsyncMock()

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.services.push_service.send_push",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            result = await send_push(title="Hello", body="World")

        assert "1 device(s)" in result


class TestScheduleJob:
    """Tests for schedule_job tool."""

    @pytest.mark.asyncio
    async def test_creates_at_job(self):
        from app.services.tools._executor_scheduling import schedule_job

        persona = _make_persona()
        session_fn, mock_db = _mock_async_session(persona)

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db.execute.return_value = mock_count_result

        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await schedule_job(
                name="Test reminder",
                schedule_type="at",
                schedule_value=future,
                payload_message="Check status",
            )

        assert "scheduled" in result
        assert "Test reminder" in result

    @pytest.mark.asyncio
    async def test_rejects_invalid_schedule_type(self):
        from app.services.tools._executor_scheduling import schedule_job

        result = await schedule_job(
            name="Bad job",
            schedule_type="invalid",
            schedule_value="foo",
            payload_message="test",
        )
        assert "Error" in result
        assert "Invalid schedule_type" in result

    @pytest.mark.asyncio
    async def test_rejects_past_at_time(self):
        from app.services.tools._executor_scheduling import schedule_job

        persona = _make_persona()
        session_fn, mock_db = _mock_async_session(persona)

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db.execute.return_value = mock_count_result

        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await schedule_job(
                name="Past job",
                schedule_type="at",
                schedule_value=past,
                payload_message="test",
            )

        assert "past" in result.lower()


class TestListScheduledJobs:
    """Tests for list_scheduled_jobs tool."""

    @pytest.mark.asyncio
    async def test_empty_list(self):
        from app.services.tools._executor_scheduling import list_scheduled_jobs

        persona = _make_persona()
        session_fn, mock_db = _mock_async_session(persona)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await list_scheduled_jobs()

        assert "No scheduled jobs" in result


class TestCancelScheduledJob:
    """Tests for cancel_scheduled_job tool."""

    @pytest.mark.asyncio
    async def test_not_found(self):
        from app.services.tools._executor_scheduling import cancel_scheduled_job

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await cancel_scheduled_job("nonexistent-id")

        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_disable_job(self):
        from app.services.tools._executor_scheduling import cancel_scheduled_job

        mock_db = AsyncMock()
        mock_job = MagicMock()
        mock_job.name = "Test job"
        mock_job.enabled = True
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await cancel_scheduled_job("some-id")

        assert "disabled" in result.lower()
        assert mock_job.enabled is False


class TestSteerConsultation:
    """Tests for steer_consultation tool."""

    @pytest.mark.asyncio
    async def test_sends_followup(self):
        from app.services.tools._executor_consultation import steer_consultation

        mock_result = MagicMock()
        mock_result.content = "Here's my follow-up advice."
        mock_result.session_id = "sess-123"

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()
        mock_redis.close = AsyncMock()

        mock_db = AsyncMock()
        mock_persona = _make_persona()
        mock_persona_result = MagicMock()
        mock_persona_result.scalar_one_or_none.return_value = mock_persona
        mock_db.execute.return_value = mock_persona_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("redis.asyncio.from_url", return_value=mock_redis),
        ):
            result = await steer_consultation("test-project", "sess-123", "Follow up question")

        assert "sess-123" in result
        assert "follow-up advice" in result

    @pytest.mark.asyncio
    async def test_no_project_id_error(self):
        from app.services.tools._executor_consultation import steer_consultation

        result = await steer_consultation(None, "sess-123", "test")
        assert "Error" in result


class TestListConsultations:
    """Tests for list_consultations tool."""

    @pytest.mark.asyncio
    async def test_empty_list(self):
        from app.services.tools._executor_consultation import list_consultations

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await list_consultations()

        assert "No consultations" in result


class TestCancelConsultation:
    """Tests for cancel_consultation tool."""

    @pytest.mark.asyncio
    async def test_closes_session(self):
        from app.services.tools._executor_consultation import cancel_consultation

        mock_db = AsyncMock()
        mock_session = MagicMock()
        mock_session.request_source = "consultation"
        mock_session.status = "active"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_session
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await cancel_consultation("sess-456")

        assert "closed" in result.lower()
        assert mock_session.status == "completed"

    @pytest.mark.asyncio
    async def test_rejects_non_consultation(self):
        from app.services.tools._executor_consultation import cancel_consultation

        mock_db = AsyncMock()
        mock_session = MagicMock()
        mock_session.request_source = "user"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_session
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await cancel_consultation("sess-456")

        assert "not a consultation" in result.lower()


class TestManageTasks:
    """Tests for manage_tasks tool."""

    @pytest.mark.asyncio
    async def test_overview(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="No tasks ready")
        result = await manage_tasks(mock_bash, action="overview")

        assert "No tasks ready" in result

    @pytest.mark.asyncio
    async def test_get_context_requires_task_id(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        result = await manage_tasks(mock_bash, action="get_context")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_create_task(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="Task #42 created")
        result = await manage_tasks(
            mock_bash,
            action="create",
            title="Test task",
            description="Test description",
            priority=1,
            task_type="feature",
            labels="complexity:simple",
        )

        assert "Task #42 created" in result

    @pytest.mark.asyncio
    async def test_create_requires_title(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        result = await manage_tasks(mock_bash, action="create")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_dispatch(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="Dispatched task 42")
        result = await manage_tasks(mock_bash, action="dispatch", task_id="42")

        assert "Dispatched" in result

    @pytest.mark.asyncio
    async def test_cleanup_status_requires_project_id(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        result = await manage_tasks(mock_bash, action="cleanup_status")

        assert "project_id required" in result
        mock_bash.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_status(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="CLEANUP[current]:repos=1 needs_cleanup=1")
        result = await manage_tasks(
            mock_bash,
            action="cleanup_status",
            project_id="agent-hub",
        )

        assert "CLEANUP[current]" in result
        mock_bash.assert_awaited_once_with("st -P agent-hub cleanup status")

    @pytest.mark.asyncio
    async def test_cleanup_worktrees_requires_project_id(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        result = await manage_tasks(mock_bash, action="cleanup_worktrees")

        assert "project_id required" in result
        mock_bash.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_worktrees(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="Cleaned 2, skipped 1, errors 0")
        result = await manage_tasks(
            mock_bash,
            action="cleanup_worktrees",
            project_id="agent-hub",
        )

        assert "Cleaned 2" in result
        mock_bash.assert_awaited_once_with("st -P agent-hub cleanup worktrees --auto")

    @pytest.mark.asyncio
    async def test_done(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="Completed task 42")
        result = await manage_tasks(
            mock_bash, action="done", task_id="42", project_id="summitflow"
        )

        assert "Completed task 42" in result
        mock_bash.assert_awaited_once_with("st -P summitflow done 42")

    @pytest.mark.asyncio
    async def test_abandon(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="Abandoned task 42")
        result = await manage_tasks(
            mock_bash, action="abandon", task_id="42", project_id="summitflow"
        )

        assert "Abandoned task 42" in result
        mock_bash.assert_awaited_once_with("st -P summitflow abandon 42")

    @pytest.mark.asyncio
    async def test_reconcile_closes_completed_lane(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="Completed task task-42")
        mock_db = AsyncMock()
        completed_session = MagicMock(
            status="completed",
            summary_oneliner="Fixed the regression",
            created_at=datetime.now(UTC),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [completed_session]
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="reconcile",
                task_id="task-42",
                project_id="summitflow",
            )

        assert "Completed task task-42" in result
        mock_bash.assert_awaited_once_with(
            "st -P summitflow done task-42 --message 'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )

    @pytest.mark.asyncio
    async def test_reconcile_falls_back_to_admin_close_when_checkpoint_is_missing(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "ERROR No checkpoint found for task-42. Was it claimed?\n",
                "Completed task task-42",
            ]
        )
        mock_db = AsyncMock()
        completed_session = MagicMock(
            status="completed",
            summary_oneliner="Fixed the regression",
            created_at=datetime.now(UTC),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [completed_session]
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="reconcile",
                task_id="task-42",
                project_id="summitflow",
            )

        assert "Completed task task-42" in result
        assert mock_bash.await_args_list[0].args[0] == (
            "st -P summitflow done task-42 --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --admin --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )

    @pytest.mark.asyncio
    async def test_reconcile_falls_back_to_admin_close_when_worktree_is_dirty(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "Claimed worktree has uncommitted changes.\n  Path: /tmp/worktree/task-42\nCommit or stash there before running st done.",
                "Completed task task-42",
            ]
        )
        mock_db = AsyncMock()
        completed_session = MagicMock(
            status="completed",
            summary_oneliner="Fixed the regression",
            created_at=datetime.now(UTC),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [completed_session]
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="reconcile",
                task_id="task-42",
                project_id="summitflow",
            )

        assert "Completed task task-42" in result
        assert mock_bash.await_args_list[0].args[0] == (
            "st -P summitflow done task-42 --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --admin --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )

    @pytest.mark.asyncio
    async def test_reconcile_falls_back_to_admin_close_when_task_is_not_ready(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "ERROR Task not ready to complete: subtasks, steps\n",
                "Completed task task-42",
            ]
        )
        mock_db = AsyncMock()
        completed_session = MagicMock(
            status="completed",
            summary_oneliner="Fixed the regression",
            created_at=datetime.now(UTC),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [completed_session]
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="reconcile",
                task_id="task-42",
                project_id="summitflow",
            )

        assert "Completed task task-42" in result
        assert mock_bash.await_args_list[0].args[0] == (
            "st -P summitflow done task-42 --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --admin --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )

    @pytest.mark.asyncio
    async def test_reconcile_cancels_orphan_running_task_without_lane_evidence(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "TASK:task-42|running|P1|task|SIMPLE",
                "No checkpoint found for task-42",
                "TASK:task-42|cancelled|P1|task|SIMPLE",
            ]
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="reconcile",
                task_id="task-42",
                project_id="summitflow",
            )

        assert "Recovered task-42" in result
        mock_bash.assert_any_await("st -P summitflow context task-42 --compact")
        mock_bash.assert_any_await("st -P summitflow checkpoints --details task-42")
        mock_bash.assert_any_await(
            "st -P summitflow cancel task-42 -r 'Recovered stale running task with no linked Agent Hub sessions or checkpoint.'"
        )

    @pytest.mark.asyncio
    async def test_reconcile_skips_orphan_running_task_when_checkpoint_still_exists(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "TASK:task-42|running|P1|task|SIMPLE",
                "CHECKPOINT:task-42|main|/tmp/worktree/task-42",
            ]
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="reconcile",
                task_id="task-42",
                project_id="summitflow",
            )

        assert "Reconcile skipped for task-42: no linked Agent Hub sessions found." in result
        mock_bash.assert_any_await("st -P summitflow context task-42 --compact")
        mock_bash.assert_any_await("st -P summitflow checkpoints --details task-42")
        assert mock_bash.await_count == 2

    @pytest.mark.asyncio
    async def test_reconcile_refuses_when_lane_is_still_active(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        mock_db = AsyncMock()
        active_session = MagicMock(
            status="active",
            agent_slug="coder",
            created_at=datetime.now(UTC),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [active_session]
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="reconcile",
                task_id="task-42",
                project_id="summitflow",
            )

        assert "still has 1 active session" in result
        mock_bash.assert_awaited_once_with("st -P summitflow context task-42 --compact")

    @pytest.mark.asyncio
    async def test_reconcile_allows_stale_active_when_task_is_blocked(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "TASK:task-42|blocked|P2|bug|SIMPLE",
                "Completed task task-42",
            ]
        )
        mock_db = AsyncMock()
        stale_active = MagicMock(
            status="active",
            current_branch="task-42/main",
            created_at=datetime.now(UTC) - timedelta(minutes=20),
            updated_at=datetime.now(UTC) - timedelta(minutes=20),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        completed = MagicMock(
            status="completed",
            current_branch="task-42/fix",
            summary_oneliner="Applied the real fix",
            created_at=datetime.now(UTC) - timedelta(minutes=1),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stale_active, completed]
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="reconcile",
                task_id="task-42",
                project_id="summitflow",
            )

        assert "Completed task task-42" in result
        assert stale_active.status == "completed"
        assert stale_active.workstream_status == "superseded"
        assert "Superseded by session on branch task-42/fix" in stale_active.workstream_note
        mock_bash.assert_any_await("st -P summitflow context task-42 --compact")

    @pytest.mark.asyncio
    async def test_reconcile_allows_stale_active_by_inactivity_even_while_task_is_running(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "TASK:task-42|running|P2|bug|SIMPLE",
                "Completed task task-42",
            ]
        )
        mock_db = AsyncMock()
        stale_active = MagicMock(
            status="active",
            current_branch="task-42/main",
            created_at=datetime.now(UTC) - timedelta(minutes=20),
            updated_at=datetime.now(UTC) - timedelta(minutes=20),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        completed = MagicMock(
            status="completed",
            current_branch="task-42/fix",
            summary_oneliner="Applied the real fix",
            created_at=datetime.now(UTC) - timedelta(minutes=1),
            updated_at=datetime.now(UTC) - timedelta(minutes=1),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stale_active, completed]
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="reconcile",
                task_id="task-42",
                project_id="summitflow",
            )

        assert "Completed task task-42" in result
        assert stale_active.status == "completed"
        assert stale_active.workstream_status == "superseded"
        assert "Superseded by session on branch task-42/fix during reconcile" in stale_active.workstream_note

    @pytest.mark.asyncio
    async def test_reconcile_marks_authoritative_and_superseded_sessions(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="Completed task task-42")
        mock_db = AsyncMock()
        older = MagicMock(
            status="completed",
            current_branch="task-42/old",
            summary_oneliner="Old branch result",
            created_at=datetime.now(UTC) - timedelta(hours=1),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        newer = MagicMock(
            status="completed",
            current_branch="task-42/main",
            summary_oneliner="Newest branch result",
            created_at=datetime.now(UTC),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [newer, older]
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            await manage_tasks(
                mock_bash,
                action="reconcile",
                task_id="task-42",
                project_id="summitflow",
            )

        assert newer.workstream_status == "authoritative"
        assert older.workstream_status == "superseded"
        assert "Superseded by session on branch task-42/main" in older.workstream_note
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_retire_lane_marks_completed_sessions_retired(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        mock_db = AsyncMock()
        completed = MagicMock(
            status="completed",
            current_branch="task-77/main",
            created_at=datetime.now(UTC),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [completed]
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="retire_lane",
                task_id="task-77",
                project_id="summitflow",
            )

        assert "Retired 1 session-backed lane(s) for task-77" in result
        assert completed.workstream_status == "retired"
        assert "Retired via manage_tasks(action=\"retire_lane\")" in completed.workstream_note
        mock_bash.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retire_lane_refuses_when_active_sessions_exist(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        mock_db = AsyncMock()
        active = MagicMock(status="active", created_at=datetime.now(UTC))
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [active]
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="retire_lane",
                task_id="task-77",
                project_id="summitflow",
            )

        assert "cannot retire while 1 active session" in result
        mock_bash.assert_awaited_once_with("st -P summitflow context task-77 --compact")

    @pytest.mark.asyncio
    async def test_retire_lane_allows_stale_active_when_task_is_terminal(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="TASK:task-77|completed|P2|task|SIMPLE")
        mock_db = AsyncMock()
        active = MagicMock(
            status="active",
            current_branch="task-77/main",
            created_at=datetime.now(UTC),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [active]
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="retire_lane",
                task_id="task-77",
                project_id="summitflow",
            )

        assert "Retired 1 session-backed lane(s) for task-77" in result
        assert active.status == "completed"
        assert active.workstream_status == "retired"
        assert "stale active" in active.workstream_note
        mock_bash.assert_awaited_once_with("st -P summitflow context task-77 --compact")

    @pytest.mark.asyncio
    async def test_retire_lane_allows_stale_active_by_inactivity_while_task_is_running(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="TASK:task-77|running|P2|task|SIMPLE")
        mock_db = AsyncMock()
        active = MagicMock(
            status="active",
            current_branch="task-77/main",
            created_at=datetime.now(UTC) - timedelta(minutes=20),
            updated_at=datetime.now(UTC) - timedelta(minutes=20),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [active]
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await manage_tasks(
                mock_bash,
                action="retire_lane",
                task_id="task-77",
                project_id="summitflow",
            )

        assert "Retired 1 session-backed lane(s) for task-77" in result
        assert active.status == "completed"
        assert active.workstream_status == "retired"
        assert "Retired stale active lane during retire_lane after" in active.workstream_note

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        result = await manage_tasks(mock_bash, action="nonsense")
        assert "Error" in result
        assert "Unknown action" in result
