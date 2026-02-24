"""Tests for persona tool handlers in direct_executor_core.py."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.persona import Persona
from app.models.persona_journal import PersonaJournal
from app.services.tools.direct_executor_core import DirectToolExecutor


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


def _make_journal(**overrides) -> MagicMock:
    """Create a mock PersonaJournal for testing."""
    defaults = {
        "id": 1,
        "persona_id": 1,
        "entry_date": date.today(),
        "content": "Observed user preference.",
        "entry_type": "observation",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=PersonaJournal)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_executor() -> DirectToolExecutor:
    """Create a DirectToolExecutor with minimal config."""
    return DirectToolExecutor(
        project_id="test-project",
    )


def _mock_async_session(persona, journal_entries=None):
    """Create a mock async_session context manager that returns a mock db.

    When get_or_create_persona is separately patched, execute is only called
    for the journal query (not the persona lookup).
    """
    mock_db = AsyncMock()

    if journal_entries is not None:
        # Only the journal query goes through execute (persona is separately patched)
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = journal_entries
        mock_db.execute.return_value = mock_result_journal
    else:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
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
        executor = _make_executor()
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
            result = await executor.read_personality()

        assert result == "I'm creative and bold."

    @pytest.mark.asyncio
    async def test_returns_placeholder_when_empty(self):
        executor = _make_executor()
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
            result = await executor.read_personality()

        assert "No personality document set" in result


class TestWritePersonality:
    """Tests for write_personality tool."""

    @pytest.mark.asyncio
    async def test_updates_personality_and_version(self):
        executor = _make_executor()
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
            result = await executor.write_personality("New personality.", "Testing")

        assert "Personality updated" in result
        assert "version 4" in result
        assert persona.personality == "New personality."
        assert persona.version == 4


class TestWriteJournal:
    """Tests for write_journal tool."""

    @pytest.mark.asyncio
    async def test_creates_entry(self):
        executor = _make_executor()
        persona = _make_persona()
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.write_journal("Learned something.", "learning")

        assert "Journal entry recorded" in result
        assert "learning" in result

    @pytest.mark.asyncio
    async def test_default_type_is_observation(self):
        executor = _make_executor()
        persona = _make_persona()
        session_fn, _ = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.write_journal("Something happened.")

        assert "observation" in result

    @pytest.mark.asyncio
    async def test_invalid_entry_type_rejected(self):
        executor = _make_executor()
        result = await executor.write_journal("Bad entry.", "nonsense")

        assert "Invalid entry_type" in result
        assert "nonsense" in result
        assert "observation" in result

    @pytest.mark.asyncio
    async def test_all_valid_entry_types_accepted(self):
        executor = _make_executor()
        persona = _make_persona()

        for entry_type in ["observation", "decision", "learning", "user_insight"]:
            session_fn, _ = _mock_async_session(persona)
            with (
                patch("app.db.async_session", session_fn),
                patch(
                    "app.services.persona_service.get_or_create_persona",
                    new_callable=AsyncMock,
                    return_value=persona,
                ),
            ):
                result = await executor.write_journal("Test.", entry_type)
                assert "Journal entry recorded" in result


class TestReadJournal:
    """Tests for read_journal tool."""

    @pytest.mark.asyncio
    async def test_returns_formatted_entries(self):
        executor = _make_executor()
        persona = _make_persona()
        entry = _make_journal(
            entry_date=date.today(),
            content="Dark mode preferred.",
            entry_type="user_insight",
        )
        session_fn, _ = _mock_async_session(persona, journal_entries=[entry])

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.read_journal()

        assert "Dark mode preferred." in result
        assert "[user_insight]" in result

    @pytest.mark.asyncio
    async def test_empty_journal(self):
        executor = _make_executor()
        persona = _make_persona()
        session_fn, _ = _mock_async_session(persona, journal_entries=[])

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.read_journal()

        assert "No journal entries" in result

    @pytest.mark.asyncio
    async def test_custom_days_back(self):
        executor = _make_executor()
        persona = _make_persona()
        session_fn, _ = _mock_async_session(persona, journal_entries=[])

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.read_journal(days_back=30)

        assert "No journal entries in the last 30 days" in result


class TestSearchJournal:
    """Tests for search_journal tool."""

    @pytest.mark.asyncio
    async def test_returns_matching_entries(self):
        executor = _make_executor()
        persona = _make_persona()
        entry = _make_journal(content="Found a dark mode bug.", entry_type="observation")
        session_fn, _ = _mock_async_session(persona, journal_entries=[entry])

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.search_journal("dark mode")

        assert "dark mode bug" in result

    @pytest.mark.asyncio
    async def test_no_matches(self):
        executor = _make_executor()
        persona = _make_persona()
        session_fn, _ = _mock_async_session(persona, journal_entries=[])

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.search_journal("nonexistent")

        assert "No journal entries matching" in result


class TestWriteUserContext:
    """Tests for write_user_context tool."""

    @pytest.mark.asyncio
    async def test_updates_user_context(self):
        executor = _make_executor()
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
            result = await executor.write_user_context("Prefers morning standups.")

        assert "User context updated" in result
        assert persona.user_context == "Prefers morning standups."
        assert persona.version == 3


class TestReadUserContext:
    """Tests for read_user_context tool."""

    @pytest.mark.asyncio
    async def test_returns_context_text(self):
        executor = _make_executor()
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
            result = await executor.read_user_context()

        assert result == "Likes verbose output."

    @pytest.mark.asyncio
    async def test_returns_placeholder_when_empty(self):
        executor = _make_executor()
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
            result = await executor.read_user_context()

        assert "No user context set" in result


class TestMarkMemoryRelevant:
    """Tests for mark_memory_relevant tool."""

    @pytest.mark.asyncio
    async def test_adds_tag(self):
        executor = _make_executor()
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
            result = await executor.mark_memory_relevant("abc12345-uuid")

        assert "marked as persona-relevant" in result
        mock_set.assert_awaited_once_with("abc12345-uuid", ["persona-relevant"])

    @pytest.mark.asyncio
    async def test_idempotent_when_already_tagged(self):
        executor = _make_executor()
        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            return_value=["persona-relevant"],
        ):
            result = await executor.mark_memory_relevant("abc12345-uuid")

        assert "already tagged" in result

    @pytest.mark.asyncio
    async def test_error_handling(self):
        executor = _make_executor()
        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            side_effect=Exception("Neo4j down"),
        ):
            result = await executor.mark_memory_relevant("bad-uuid")

        assert "Error" in result


class TestMarkMemoryIrrelevant:
    """Tests for mark_memory_irrelevant tool."""

    @pytest.mark.asyncio
    async def test_removes_tag(self):
        executor = _make_executor()
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
            result = await executor.mark_memory_irrelevant("abc12345-uuid")

        assert "Removed persona-relevant" in result
        mock_set.assert_awaited_once_with("abc12345-uuid", ["other-tag"])

    @pytest.mark.asyncio
    async def test_idempotent_when_not_tagged(self):
        executor = _make_executor()
        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            return_value=["other-tag"],
        ):
            result = await executor.mark_memory_irrelevant("abc12345-uuid")

        assert "not tagged as persona-relevant" in result

    @pytest.mark.asyncio
    async def test_error_handling(self):
        executor = _make_executor()
        with patch(
            "app.services.memory.episode_property_queries.get_episode_tags",
            new_callable=AsyncMock,
            side_effect=Exception("Connection lost"),
        ):
            result = await executor.mark_memory_irrelevant("bad-uuid")

        assert "Error" in result


class TestSubmitOnboarding:
    """Tests for submit_onboarding tool."""

    @pytest.mark.asyncio
    async def test_approved_returns_confirmation(self):
        executor = _make_executor()
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
            result = await executor.submit_onboarding("Full onboarding summary")

        assert "APPROVED" in result
        assert "All good." in result

    @pytest.mark.asyncio
    async def test_rejected_returns_feedback(self):
        executor = _make_executor()
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
            result = await executor.submit_onboarding("Partial summary")

        assert "REJECTED" in result
        assert "Missing schedule." in result

    @pytest.mark.asyncio
    async def test_error_handling(self):
        executor = _make_executor()
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
            result = await executor.submit_onboarding("Summary")

        assert "Error" in result


class TestSendPush:
    """Tests for send_push tool."""

    @pytest.mark.asyncio
    async def test_sends_notification(self):
        executor = _make_executor()
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
            result = await executor.send_push(
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
        executor = _make_executor()
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
            result = await executor.send_push(title="Hello", body="World")

        assert "1 device(s)" in result


class TestScheduleJob:
    """Tests for schedule_job tool."""

    @pytest.mark.asyncio
    async def test_creates_at_job(self):
        executor = _make_executor()
        persona = _make_persona()
        session_fn, mock_db = _mock_async_session(persona)

        # Mock the count query
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
            result = await executor.schedule_job(
                name="Test reminder",
                schedule_type="at",
                schedule_value=future,
                payload_message="Check status",
            )

        assert "scheduled" in result
        assert "Test reminder" in result

    @pytest.mark.asyncio
    async def test_rejects_invalid_schedule_type(self):
        executor = _make_executor()
        result = await executor.schedule_job(
            name="Bad job",
            schedule_type="invalid",
            schedule_value="foo",
            payload_message="test",
        )
        assert "Error" in result
        assert "Invalid schedule_type" in result

    @pytest.mark.asyncio
    async def test_rejects_past_at_time(self):
        executor = _make_executor()
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
            result = await executor.schedule_job(
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
        executor = _make_executor()
        persona = _make_persona()
        session_fn, mock_db = _mock_async_session(persona, journal_entries=[])

        # Override execute for the job query
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
            result = await executor.list_scheduled_jobs()

        assert "No scheduled jobs" in result


class TestCancelScheduledJob:
    """Tests for cancel_scheduled_job tool."""

    @pytest.mark.asyncio
    async def test_not_found(self):
        executor = _make_executor()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await executor.cancel_scheduled_job("nonexistent-id")

        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_disable_job(self):
        executor = _make_executor()
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
            result = await executor.cancel_scheduled_job("some-id")

        assert "disabled" in result.lower()
        assert mock_job.enabled is False


class TestSteerConsultation:
    """Tests for steer_consultation tool."""

    @pytest.mark.asyncio
    async def test_sends_followup(self):
        executor = _make_executor()

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
            result = await executor.steer_consultation("sess-123", "Follow up question")

        assert "sess-123" in result
        assert "follow-up advice" in result

    @pytest.mark.asyncio
    async def test_no_project_id_error(self):
        executor = DirectToolExecutor()
        result = await executor.steer_consultation("sess-123", "test")
        assert "Error" in result


class TestListConsultations:
    """Tests for list_consultations tool."""

    @pytest.mark.asyncio
    async def test_empty_list(self):
        executor = _make_executor()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await executor.list_consultations()

        assert "No consultations" in result


class TestCancelConsultation:
    """Tests for cancel_consultation tool."""

    @pytest.mark.asyncio
    async def test_closes_session(self):
        executor = _make_executor()
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
            result = await executor.cancel_consultation("sess-456")

        assert "closed" in result.lower()
        assert mock_session.status == "completed"

    @pytest.mark.asyncio
    async def test_rejects_non_consultation(self):
        executor = _make_executor()
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
            result = await executor.cancel_consultation("sess-456")

        assert "not a consultation" in result.lower()


class TestManageTasks:
    """Tests for manage_tasks tool."""

    @pytest.mark.asyncio
    async def test_list_ready(self):
        executor = _make_executor()
        with patch.object(executor, "bash", new_callable=AsyncMock, return_value="No tasks ready"):
            result = await executor.manage_tasks(action="list_ready")

        assert "No tasks ready" in result

    @pytest.mark.asyncio
    async def test_get_context_requires_task_id(self):
        executor = _make_executor()
        result = await executor.manage_tasks(action="get_context")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_create_task(self):
        executor = _make_executor()
        with patch.object(
            executor, "bash", new_callable=AsyncMock, return_value="Task #42 created"
        ):
            result = await executor.manage_tasks(
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
        executor = _make_executor()
        result = await executor.manage_tasks(action="create")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_dispatch(self):
        executor = _make_executor()
        with patch.object(
            executor, "bash", new_callable=AsyncMock, return_value="Dispatched task 42"
        ):
            result = await executor.manage_tasks(action="dispatch", task_id="42")

        assert "Dispatched" in result

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        executor = _make_executor()
        result = await executor.manage_tasks(action="nonsense")
        assert "Error" in result
        assert "Unknown action" in result
