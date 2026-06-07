"""Tests for persona-related tool implementations in executor sub-modules."""

from __future__ import annotations

import json
import shlex
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.models.persona import Persona


def _make_persona(**overrides) -> MagicMock:
    """Create a mock Persona with sensible defaults."""
    defaults = {
        "id": 1,
        "agent_id": 10,
        "name": "Persona",
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


def _allow_execution_permission_patch(
    *,
    permission_tier: str = "full",
    auto_exec_enabled: bool = True,
    in_time_window: bool = True,
    reason: str = "allowed",
):
    from app.services.project_permission_service import ExecutionPermissionResult

    return patch(
        "app.services.tools._executor_io_tasks.check_execution_permission",
        new=AsyncMock(
            return_value=ExecutionPermissionResult(
                allowed=auto_exec_enabled and in_time_window and permission_tier != "off",
                permission_tier=permission_tier,
                auto_exec_enabled=auto_exec_enabled,
                in_time_window=in_time_window,
                reason=reason,
            )
        ),
    )


@pytest.fixture(autouse=True)
def _mock_prompt_backed_persona_documents():
    async def _get_personality(db):
        result = await db.execute(object())
        persona = result.scalar_one_or_none()
        if persona is None:
            return None
        return getattr(persona, "personality", None)

    async def _set_personality(db, personality, **_kwargs):
        result = await db.execute(object())
        persona = result.scalar_one_or_none()
        old_text = (getattr(persona, "personality", "") or "").strip()
        new_text = personality.strip()
        persona.personality_previous = old_text or None
        persona.personality = new_text
        return len(old_text), len(new_text)

    async def _get_user_context(db):
        result = await db.execute(object())
        persona = result.scalar_one_or_none()
        if persona is None:
            return None
        return getattr(persona, "user_context", None)

    async def _set_user_context(db, user_context, **_kwargs):
        result = await db.execute(object())
        persona = result.scalar_one_or_none()
        old_text = (getattr(persona, "user_context", "") or "").strip()
        new_text = user_context.strip()
        persona.user_context_previous = old_text or None
        persona.user_context = new_text
        return len(old_text), len(new_text)

    with (
        patch(
            "app.services.persona_document_prompt_service.get_persona_personality_document",
            new=_get_personality,
        ),
        patch(
            "app.services.persona_document_prompt_service.set_persona_personality_document",
            new=_set_personality,
        ),
        patch(
            "app.services.persona_document_prompt_service.get_persona_user_context_document",
            new=_get_user_context,
        ),
        patch(
            "app.services.persona_document_prompt_service.set_persona_user_context_document",
            new=_set_user_context,
        ),
    ):
        yield


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

    _full_uuid = "abc12345-0000-4000-8000-000000000000"
    _resolve_patch = "app.services.memory.memory_utils.resolve_uuid_prefix"

    @pytest.mark.asyncio
    async def test_adds_tag(self):
        from app.services.tools._executor_persona import mark_memory_relevant

        with (
            patch(self._resolve_patch, new_callable=AsyncMock, return_value=self._full_uuid),
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
            result = await mark_memory_relevant("abc12345")

        assert "marked as persona-relevant" in result
        mock_set.assert_awaited_once_with(self._full_uuid, ["persona-relevant"])

    @pytest.mark.asyncio
    async def test_idempotent_when_already_tagged(self):
        from app.services.tools._executor_persona import mark_memory_relevant

        with (
            patch(self._resolve_patch, new_callable=AsyncMock, return_value=self._full_uuid),
            patch(
                "app.services.memory.episode_property_queries.get_episode_tags",
                new_callable=AsyncMock,
                return_value=["persona-relevant"],
            ),
        ):
            result = await mark_memory_relevant("abc12345")

        assert "already tagged" in result

    @pytest.mark.asyncio
    async def test_error_handling(self):
        from app.services.tools._executor_persona import mark_memory_relevant

        with patch(
            self._resolve_patch,
            new_callable=AsyncMock,
            side_effect=Exception("Database error"),
        ):
            result = await mark_memory_relevant("abc12345")

        assert "Error" in result


class TestMarkMemoryIrrelevant:
    """Tests for mark_memory_irrelevant tool."""

    @pytest.mark.asyncio
    async def test_removes_tag(self):
        from app.services.tools._executor_persona import mark_memory_irrelevant

        full_uuid = "abc12345-0000-4000-8000-000000000000"
        with (
            patch(
                "app.services.memory.memory_utils.resolve_uuid_prefix",
                new_callable=AsyncMock,
                return_value=full_uuid,
            ),
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
            result = await mark_memory_irrelevant("abc12345")

        assert "Removed persona-relevant" in result
        mock_set.assert_awaited_once_with(full_uuid, ["other-tag"])

    @pytest.mark.asyncio
    async def test_idempotent_when_not_tagged(self):
        from app.services.tools._executor_persona import mark_memory_irrelevant

        with (
            patch(
                "app.services.memory.memory_utils.resolve_uuid_prefix",
                new_callable=AsyncMock,
                return_value="abc12345-0000-4000-8000-000000000000",
            ),
            patch(
                "app.services.memory.episode_property_queries.get_episode_tags",
                new_callable=AsyncMock,
                return_value=["other-tag"],
            ),
        ):
            result = await mark_memory_irrelevant("abc12345")

        assert "not tagged as persona-relevant" in result

    @pytest.mark.asyncio
    async def test_error_handling(self):
        from app.services.tools._executor_persona import mark_memory_irrelevant

        with patch(
            "app.services.memory.memory_utils.resolve_uuid_prefix",
            new_callable=AsyncMock,
            side_effect=Exception("Connection lost"),
        ):
            result = await mark_memory_irrelevant("abc12345")

        assert "Error" in result


class TestManageMemoryTags:
    """Tests for the generic memory-tag management tool."""

    _full_uuid = "abc12345-0000-4000-8000-000000000000"
    _resolve_patch = "app.services.memory.memory_utils.resolve_uuid_prefix"

    @pytest.mark.asyncio
    async def test_get_tags_returns_current_tags(self):
        from app.services.tools._executor_persona import manage_memory_tags

        with (
            patch(self._resolve_patch, new_callable=AsyncMock, return_value=self._full_uuid),
            patch(
                "app.services.memory.episode_property_queries.get_episode_tags",
                new_callable=AsyncMock,
                return_value=["debugger-relevant", "oauth"],
            ),
        ):
            result = await manage_memory_tags("get_tags", "abc12345", None)

        assert "debugger-relevant" in result
        assert "oauth" in result

    @pytest.mark.asyncio
    async def test_add_tags_merges_without_duplicates(self):
        from app.services.tools._executor_persona import manage_memory_tags

        with (
            patch(self._resolve_patch, new_callable=AsyncMock, return_value=self._full_uuid),
            patch(
                "app.services.memory.episode_property_queries.get_episode_tags",
                new_callable=AsyncMock,
                return_value=["debugger-relevant"],
            ),
            patch(
                "app.services.memory.episode_property_setters.set_episode_tags",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_set,
        ):
            result = await manage_memory_tags(
                "add_tags",
                "abc12345",
                ["debugger-relevant", "oauth"],
            )

        assert "Updated tags for memory abc12345" in result
        mock_set.assert_awaited_once_with(self._full_uuid, ["debugger-relevant", "oauth"])

    @pytest.mark.asyncio
    async def test_remove_tags_updates_memory(self):
        from app.services.tools._executor_persona import manage_memory_tags

        with (
            patch(self._resolve_patch, new_callable=AsyncMock, return_value=self._full_uuid),
            patch(
                "app.services.memory.episode_property_queries.get_episode_tags",
                new_callable=AsyncMock,
                return_value=["debugger-relevant", "oauth"],
            ),
            patch(
                "app.services.memory.episode_property_setters.set_episode_tags",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_set,
        ):
            result = await manage_memory_tags(
                "remove_tags",
                "abc12345",
                ["oauth"],
            )

        assert "Updated tags for memory abc12345" in result
        mock_set.assert_awaited_once_with(self._full_uuid, ["debugger-relevant"])


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
    async def test_rejects_invalid_payload_type(self):
        from app.services.tools._executor_scheduling import schedule_job

        result = await schedule_job(
            name="Bad payload",
            schedule_type="every",
            schedule_value="60000",
            payload_message="test",
            payload_type="invalid",
        )

        assert "Error" in result
        assert "Invalid payload_type" in result

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

    @pytest.mark.asyncio
    async def test_creates_self_honing_job(self):
        from app.services.tools._executor_scheduling import schedule_job

        persona = _make_persona()
        session_fn, mock_db = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await schedule_job(
                name="Nightly self-honing",
                schedule_type="cron",
                schedule_value="0 4 * * *",
                payload_message="Nightly persona self-honing",
                payload_type="self_honing",
            )

        assert "scheduled" in result
        added_job = mock_db.add.call_args.args[0]
        assert added_job.payload_type == "self_honing"

    @pytest.mark.asyncio
    async def test_creates_memory_review_job(self):
        from app.services.tools._executor_scheduling import schedule_job

        persona = _make_persona()
        session_fn, mock_db = _mock_async_session(persona)

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await schedule_job(
                name="Memory review",
                schedule_type="cron",
                schedule_value="0 */6 * * *",
                payload_message='{"batch_limit": 25}',
                payload_type="memory_review",
            )

        assert "scheduled" in result
        added_job = mock_db.add.call_args.args[0]
        assert added_job.payload_type == "memory_review"


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

    @pytest.mark.asyncio
    async def test_lists_payload_type(self):
        from app.services.tools._executor_scheduling import list_scheduled_jobs

        persona = _make_persona()
        session_fn, mock_db = _mock_async_session(persona)
        mock_job = MagicMock()
        mock_job.name = "Nightly self-honing"
        mock_job.id = "job-1"
        mock_job.schedule_type = "cron"
        mock_job.schedule_value = "0 4 * * *"
        mock_job.payload_type = "self_honing"
        mock_job.next_run_at = datetime.now(UTC)
        mock_job.run_count = 0
        mock_job.max_runs = None
        mock_job.enabled = True
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_job]
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

        assert "type=self_honing" in result


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
    async def test_consult_agent_uses_minimal_read_only_tools(self):
        from app.services.tools._executor_consultation import consult_agent

        mock_result = MagicMock()
        mock_result.content = "Here's my advice."
        mock_result.session_id = "sess-456"

        mock_db = AsyncMock()
        mock_persona = _make_persona(limits={"max_turns": 500})
        mock_persona_result = MagicMock()
        mock_persona_result.scalar_one_or_none.return_value = mock_persona
        mock_db.execute.return_value = mock_persona_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        resolved = MagicMock()
        resolved.model = "gpt-5.4"
        resolved.provider = "codex"
        resolved.agent = MagicMock()
        resolved.agent.temperature = 0.2

        mandate = MagicMock(system_content="Consultation system prompt")

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.services.agent_routing_utils.resolve_agent",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                "app.services.agent_routing_utils.inject_agent_mandates",
                new_callable=AsyncMock,
                return_value=mandate,
            ),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_complete,
        ):
            result = await consult_agent(
                "test-project",
                "supervisor",
                "What should I verify next?",
                "Changed the web research path.",
                parent_session_id="parent-session-123",
            )

        assert "sess-456" in result
        complete_args = mock_complete.await_args
        assert complete_args is not None
        kwargs = complete_args.kwargs
        tool_names = {tool["name"] for tool in kwargs["tools"]}
        assert kwargs["execute_tools"] is True
        assert kwargs["max_turns"] == 500
        assert kwargs["parent_session_id"] == "parent-session-123"
        # Read tier = read_file + read-only web research ops. The consultant
        # gets both file reads and web research as their minimal toolkit.
        assert tool_names == {
            "read_file",
            "research_web",
            "search_web",
            "fetch_web_page",
        }

    @pytest.mark.asyncio
    async def test_sends_followup(self):
        from app.services.tools._executor_consultation import steer_consultation

        mock_result = MagicMock()
        mock_result.content = "Here's my follow-up advice."
        mock_result.session_id = "sess-123"
        mock_session = MagicMock()
        mock_session.request_source = "consultation"
        mock_session.agent_slug = "analyst"
        mock_resolved = MagicMock()
        mock_resolved.model = "codex/gpt-5.4"
        mock_resolved.provider = "codex"
        mock_resolved.agent = MagicMock(temperature=0.1, thinking_level="low")

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()
        mock_redis.close = AsyncMock()

        mock_db = AsyncMock()
        mock_persona = _make_persona()
        mock_persona_result = MagicMock()
        mock_persona_result.scalar_one_or_none.return_value = mock_persona
        mock_db.execute.return_value = mock_persona_result
        mock_db.get = AsyncMock(return_value=mock_session)

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_complete,
            patch(
                "app.services.agent_routing_utils.resolve_agent",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch("redis.asyncio.from_url", return_value=mock_redis),
        ):
            result = await steer_consultation("test-project", "sess-123", "Follow up question")

        assert "sess-123" in result
        assert "follow-up advice" in result
        complete_args = mock_complete.await_args
        assert complete_args is not None
        kwargs = complete_args.kwargs
        tool_names = {tool["name"] for tool in kwargs["tools"]}
        assert kwargs["execute_tools"] is True
        assert kwargs["max_turns"] == 500
        assert kwargs["model"] == "codex/gpt-5.4"
        assert kwargs["provider"] == "codex"
        assert kwargs["agent_slug"] == "analyst"
        assert kwargs["thinking_level"] == "low"
        assert kwargs["use_memory"] is True
        assert kwargs["memory_group_id"] == "project-test-project"
        assert tool_names == {
            "read_file",
            "research_web",
            "search_web",
            "fetch_web_page",
        }

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

    def test_manage_tasks_tool_schema_exposes_rich_plan_contract(self):
        from app.services.tools._persona_ops_tools import MANAGE_TASKS_TOOL

        properties = MANAGE_TASKS_TOOL.input_schema["properties"]
        subtask_properties = properties["subtasks"]["items"]["properties"]
        step_item = subtask_properties["steps"]["items"]["anyOf"][1]

        assert "objective" in properties
        assert "constraints" in properties
        assert "testing_strategy" in properties
        assert "context" in properties
        assert "phase" in subtask_properties
        assert "steps" in subtask_properties
        assert step_item["properties"]["spec"]["description"] == (
            "Free-form step metadata such as verify_command"
        )

    @pytest.mark.asyncio
    async def test_overview(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            return_value=(
                "READY-ALL[1 ready, 0 blocked, 0 active, 0 stale across 1 projects]\n\n"
                "agent-hub (1 ready)\n"
                "    task-52831804 P3 refactor [A] Refactor: backend/app/services/tools/_executor_consultation.py\n"
            )
        )
        result = await manage_tasks(mock_bash, action="overview")

        assert "READY-ALL[1 ready" in result
        assert "ACTIONABLE-READY[1]" in result
        assert "task-52831804" in result

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
    async def test_create_task_preserves_rich_plan_fields_in_generated_plan(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="IMPORT:task-123|STANDARD|1 subtasks")

        result = await manage_tasks(
            mock_bash,
            action="create",
            title="Preserve plan shape",
            description="Keep rich metadata.",
            priority=1,
            task_type="feature",
            labels="planning,persona",
            done_when=["Task context keeps rich metadata"],
            complexity="STANDARD",
            objective="Preserve rich plan metadata.",
            constraints=["Keep thin-schema callers working."],
            spirit_anti="No duplicate schema.",
            testing_strategy="Run focused tests and inspect the generated plan payload.",
            context={
                "files_to_modify": ["backend/app/services/tools/_executor_io_tasks.py"],
                "risks": ["Schema drift"],
                "references": [{"title": "Schema", "url": "https://github.com/elias-leslie/summitflow/schemas/plan.json"}],
                "second_opinion": {
                    "required": True,
                    "stage": "task_shape",
                    "status": "pending",
                    "summary": "Needs contract review."
                }
            },
            subtasks=[
                {
                    "id": "1.1",
                    "phase": "backend",
                    "description": "Carry structured step metadata",
                    "subtask_type": "backend",
                    "steps": [
                        {
                            "description": "Preserve verify metadata.",
                            "spec": {"verify_command": "dt pytest backend/tests/tools/test_persona_tools.py"}
                        }
                    ]
                }
            ],
            project_id="agent-hub",
        )

        assert result == "IMPORT:task-123|STANDARD|1 subtasks"
        bash_args = mock_bash.await_args
        assert bash_args is not None
        command = bash_args.args[0]
        plan_path = Path(shlex.split(command)[-1])
        try:
            payload = json.loads(plan_path.read_text())
        finally:
            plan_path.unlink(missing_ok=True)

        assert command.startswith("st -P agent-hub create --plan ")
        assert payload["task_type"] == "feature"
        assert payload["priority"] == 1
        assert payload["objective"] == "Preserve rich plan metadata."
        assert payload["constraints"] == ["Keep thin-schema callers working."]
        assert payload["spirit_anti"] == "No duplicate schema."
        assert payload["testing_strategy"] == "Run focused tests and inspect the generated plan payload."
        assert payload["context"]["files_to_modify"] == ["backend/app/services/tools/_executor_io_tasks.py"]
        assert payload["subtasks"][0]["phase"] == "backend"
        assert payload["subtasks"][0]["steps"][0]["spec"]["verify_command"] == (
            "dt pytest backend/tests/tools/test_persona_tools.py"
        )

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
    async def test_dispatch_blocks_when_project_access_is_manual(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()

        with (
            _allow_execution_permission_patch(
                permission_tier="read",
                auto_exec_enabled=False,
                in_time_window=True,
                reason="auto_exec_disabled",
            ),
        ):
            result = await manage_tasks(
                mock_bash,
                action="dispatch",
                task_id="task-42",
                project_id="a-term",
            )

        assert "Dispatch blocked" in result
        assert "a-term" in result
        assert "read/manual" in result
        assert "observe-only" in result
        assert mock_bash.await_count == 0

    @pytest.mark.asyncio
    async def test_dispatch_warns_on_running_tasks_and_cleanup_residue(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=2 dirty=0 orphan=1 prunable=0\n"
                "agent-hub checkpoints:2 dirty:0 orphan:1 prunable:0 finalize:task-old conflicts:task-conflict",
            ]
        )

        with (
            _allow_execution_permission_patch(),
            patch(
                "app.workflows._heartbeat_data._query_recent_workstream_sessions",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await manage_tasks(
                mock_bash,
                action="dispatch",
                task_id="42",
                project_id="agent-hub",
            )

        assert "Dispatch blocked" in result
        assert "cleanup residue" in result
        assert "ACTIONABLE-CLEANUP[2]" in result
        assert "agent-hub | finalize | task-old" in result
        assert "agent-hub | conflicts | task-conflict" in result
        assert mock_bash.await_count == 1

    @pytest.mark.asyncio
    async def test_dispatch_warns_on_running_tasks_when_cleanup_is_clear(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=2 dirty=0 orphan=1 prunable=0\nagent-hub checkpoints:2 dirty:0 orphan:1 prunable:0 tasks:task-1",
                '[{"id":"task-running"}]',
                '{"task_id":"42","status":"queued"}',
            ]
        )

        with _allow_execution_permission_patch():
            result = await manage_tasks(
                mock_bash,
                action="dispatch",
                task_id="42",
                project_id="agent-hub",
            )

        assert "task(s) already running" in result
        assert '"status":"queued"' in result
        assert mock_bash.await_count == 3

    @pytest.mark.asyncio
    async def test_dispatch_allows_finalize_only_cleanup_residue_with_warning(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=2 dirty=0 orphan=0 prunable=0\n"
                "agent-hub checkpoints:2 dirty:0 orphan:0 prunable:0 tasks:task-old finalize:task-old",
                "[]",
                '{"task_id":"42","status":"queued"}',
            ]
        )

        with _allow_execution_permission_patch():
            result = await manage_tasks(
                mock_bash,
                action="dispatch",
                task_id="42",
                project_id="agent-hub",
            )

        assert "WARNING: merge-ready residue detected in cleanup status." in result
        assert '"status":"queued"' in result
        assert mock_bash.await_count == 3

    @pytest.mark.asyncio
    async def test_dispatch_blocks_when_same_task_has_fresh_active_session(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=1 dirty=0 orphan=0 prunable=0\n"
                "agent-hub checkpoints:1 dirty:0 orphan:0 prunable:0 tasks:task-42",
                "TASK:task-42|running|P2|task|SIMPLE",
            ]
        )
        mock_db = AsyncMock()
        active_session = MagicMock(
            status="active",
            created_at=datetime.now(UTC) - timedelta(minutes=2),
            updated_at=datetime.now(UTC) - timedelta(minutes=2),
            workstream_updated_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [active_session]
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            _allow_execution_permission_patch(),
        ):
            result = await manage_tasks(
                mock_bash,
                action="dispatch",
                task_id="task-42",
                project_id="agent-hub",
            )

        assert "Dispatch blocked for task-42" in result
        assert "same task already has 1 active session" in result
        assert "fresh progress" in result
        assert "Wait or monitor" in result
        assert mock_bash.await_count == 2

    @pytest.mark.asyncio
    async def test_dispatch_blocks_when_running_task_has_recent_execution_activity(self):
        from app.services.tools._executor_io import manage_tasks

        recent_line = (
            f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}|INFO|Starting autonomous execution"
        )
        mock_bash = AsyncMock(
            side_effect=[
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=1 dirty=0 orphan=0 prunable=0\n"
                "agent-hub checkpoints:1 dirty:0 orphan:0 prunable:0 tasks:task-42",
                "TASK:task-42|running|P2|task|SIMPLE",
                f"{recent_line}\n",
            ]
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            _allow_execution_permission_patch(),
        ):
            result = await manage_tasks(
                mock_bash,
                action="dispatch",
                task_id="task-42",
                project_id="agent-hub",
            )

        assert "Dispatch blocked for task-42" in result
        assert "recent autonomous activity" in result
        assert "Wait or inspect" in result
        assert mock_bash.await_count == 3

    @pytest.mark.asyncio
    async def test_dispatch_blocks_running_task_without_fresh_session_evidence(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=1 dirty=0 orphan=0 prunable=0\n"
                "agent-hub checkpoints:1 dirty:0 orphan:0 prunable:0 tasks:task-42",
                "TASK:task-42|running|P2|task|SIMPLE",
                "",
            ]
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            _allow_execution_permission_patch(),
        ):
            result = await manage_tasks(
                mock_bash,
                action="dispatch",
                task_id="task-42",
                project_id="agent-hub",
            )

        assert "Dispatch blocked for task-42" in result
        assert "already running" in result
        assert "Inspect or reconcile" in result
        assert mock_bash.await_count == 3

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

        mock_bash = AsyncMock(
            side_effect=[
                (
                    "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=1 dirty=0 orphan=3 prunable=0\n"
                    "agent-hub checkpoints:1 dirty:0 orphan:3 prunable:0 tasks:task-aa44180c finalize:task-aa44180c"
                ),
            ]
        )
        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new=AsyncMock(return_value=[]),
        ):
            result = await manage_tasks(
                mock_bash,
                action="cleanup_status",
                project_id="agent-hub",
            )

        assert "CLEANUP[current]" in result
        assert "ACTIONABLE-CLEANUP[1]" in result
        assert "agent-hub | finalize | task-aa44180c" in result
        assert mock_bash.await_args_list == [
            call("st -P agent-hub cleanup status"),
        ]

    @pytest.mark.asyncio
    async def test_cleanup_status_omits_reconciled_authoritative_residue(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            return_value=(
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=3 dirty=0 orphan=0 prunable=0\n"
                "agent-hub checkpoints:3 dirty:0 orphan:0 prunable:0 review:task-ff895807,task-live1234"
            )
        )

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new=AsyncMock(
                return_value=[
                    {
                        "project_id": "agent-hub",
                        "external_id": "task-ff895807",
                        "current_branch": "task-ff895807/main",
                        "status": "completed",
                        "workstream_status": "authoritative",
                    },
                    {
                        "project_id": "agent-hub",
                        "external_id": "task-ff895807",
                        "current_branch": "task-ff895807/old",
                        "status": "completed",
                        "workstream_status": "superseded",
                    },
                ]
            ),
        ):
            result = await manage_tasks(
                mock_bash,
                action="cleanup_status",
                project_id="agent-hub",
            )

        assert "ACTIONABLE-CLEANUP[1]" in result
        assert "ACTIONABLE-CLEANUP[0]" not in result
        assert "agent-hub | review | task-live1234" in result
        assert "agent-hub | review | task-ff895807" not in result

    @pytest.mark.asyncio
    async def test_cleanup_status_reports_zero_actionable_when_all_residue_is_reconciled(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            return_value=(
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=3 dirty=0 orphan=0 prunable=0\n"
                "agent-hub checkpoints:3 dirty:0 orphan:0 prunable:0 review:task-ff895807"
            )
        )

        with patch(
            "app.workflows._heartbeat_data._query_recent_workstream_sessions",
            new=AsyncMock(
                return_value=[
                    {
                        "project_id": "agent-hub",
                        "external_id": "task-ff895807",
                        "current_branch": "task-ff895807/main",
                        "status": "completed",
                        "workstream_status": "authoritative",
                    },
                    {
                        "project_id": "agent-hub",
                        "external_id": "task-ff895807",
                        "current_branch": "task-ff895807/old",
                        "status": "completed",
                        "workstream_status": "superseded",
                    },
                ]
            ),
        ):
            result = await manage_tasks(
                mock_bash,
                action="cleanup_status",
                project_id="agent-hub",
            )

        assert "ACTIONABLE-CLEANUP[0]" in result
        assert "already reconciled authoritative/superseded" in result

    @pytest.mark.asyncio
    async def test_dispatch_ignores_reconciled_cleanup_review_residue(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                (
                    "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=3 dirty=0 orphan=0 prunable=0\n"
                    "agent-hub checkpoints:3 dirty:0 orphan:0 prunable:0 review:task-ff895807"
                ),
                '{"task_id":"task-42","status":"queued"}',
            ]
        )

        with (
            _allow_execution_permission_patch(),
            patch(
                "app.workflows._heartbeat_data._query_recent_workstream_sessions",
                new=AsyncMock(
                    return_value=[
                        {
                            "project_id": "agent-hub",
                            "external_id": "task-ff895807",
                            "current_branch": "task-ff895807/main",
                            "status": "completed",
                            "workstream_status": "authoritative",
                        },
                        {
                            "project_id": "agent-hub",
                            "external_id": "task-ff895807",
                            "current_branch": "task-ff895807/old",
                            "status": "completed",
                            "workstream_status": "superseded",
                        },
                    ]
                ),
            ),
            patch(
                "app.services.tools._executor_io_tasks._live_dispatch_block_reason",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.tools._executor_io_tasks._build_dispatch_warning",
                new=AsyncMock(return_value=""),
            ),
        ):
            result = await manage_tasks(
                mock_bash,
                action="dispatch",
                task_id="task-42",
                project_id="agent-hub",
            )

        assert '"status":"queued"' in result
        assert "Dispatch blocked" not in result

    @pytest.mark.asyncio
    async def test_cleanup_checkouts_requires_project_id(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        result = await manage_tasks(mock_bash, action="cleanup_checkpoints")

        assert "project_id required" in result
        mock_bash.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_checkouts(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(side_effect=[
            "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=1 dirty=0 orphan=0 prunable=0\n"
            "agent-hub checkpoints:1 dirty:0 orphan:0 prunable:0 tasks:task-1",
            "Cleaned 2, skipped 1, errors 0\n  Pruned closed orphan task branches: 0",
        ])
        result = await manage_tasks(
            mock_bash,
            action="cleanup_checkpoints",
            project_id="agent-hub",
        )

        assert "Cleaned 2" in result
        assert mock_bash.await_args_list == [
            call("st -P agent-hub cleanup status"),
            call("st -P agent-hub cleanup checkpoints --auto"),
        ]

    @pytest.mark.asyncio
    async def test_cleanup_checkouts_with_orphan_branches_still_runs_auto_cleanup(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(side_effect=[
            (
                "CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=0 dirty=0 orphan=1 prunable=0\n"
                "agent-hub checkpoints:0 dirty:0 orphan:1 prunable:0 orphan_branches:task-aa44180c/main"
            ),
            "No checkpoints found\n  Pruned git checkpoint registrations in 1 repo(s)\n  Pruned merged orphan task branches: 0\n  Pruned closed orphan task branches: 1",
        ])
        result = await manage_tasks(
            mock_bash,
            action="cleanup_checkpoints",
            project_id="agent-hub",
        )

        assert "Pruned closed orphan task branches: 1" in result
        assert "ACTIONABLE-CLEANUP[1]" in result
        assert "agent-hub | orphan_branch | task-aa44180c" in result
        assert mock_bash.await_args_list == [
            call("st -P agent-hub cleanup status"),
            call("st -P agent-hub cleanup checkpoints --auto"),
        ]

    @pytest.mark.asyncio
    async def test_cleanup_checkouts_with_no_residue_returns_complete_noop(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            return_value=(
                "CLEANUP[current]:repos=1 needs_cleanup=0 checkpoints=0 dirty=0 orphan=0 prunable=0\n"
                "agent-hub clean"
            )
        )
        result = await manage_tasks(
            mock_bash,
            action="cleanup_checkpoints",
            project_id="agent-hub",
        )

        assert "Cleanup complete for agent-hub." in result
        mock_bash.assert_awaited_once_with("st -P agent-hub cleanup status")

    @pytest.mark.asyncio
    async def test_cleanup_salvage_orphan_requires_task_id(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        result = await manage_tasks(
            mock_bash,
            action="salvage_orphan",
            project_id="summitflow",
        )

        assert "task_id required" in result
        mock_bash.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_salvage_orphan_requires_project_id(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        result = await manage_tasks(
            mock_bash,
            action="salvage_orphan",
            task_id="task-24310aaf",
        )

        assert "project_id required" in result
        mock_bash.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_salvage_orphan_routes_to_cli(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="Recovered orphan branch task-24310aaf/main into task task-24310aaf")
        result = await manage_tasks(
            mock_bash,
            action="salvage_orphan",
            task_id="task-24310aaf",
            project_id="summitflow",
        )

        assert "Recovered orphan branch" in result
        mock_bash.assert_awaited_once_with("st -P summitflow cleanup salvage task-24310aaf")

    @pytest.mark.asyncio
    async def test_cleanup_all_safe_exhausts_cross_project_safe_cleanup(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(side_effect=[
            (
                "CLEANUP[all]:repos=5 needs_cleanup=5 checkpoints=6 dirty=0 orphan=18 prunable=4\n"
                "agent-hub checkpoints:1 dirty:0 orphan:7 prunable:3\n"
                "a-term checkpoints:1 dirty:0 orphan:3 prunable:1"
            ),
            "Cleaned 0, skipped 0, errors 0\n  Pruned git checkpoint registrations in 5 repo(s)\n  Pruned merged orphan task branches: 4\n  Pruned closed orphan task branches: 10",
            (
                "CLEANUP[all]:repos=5 needs_cleanup=2 checkpoints=4 dirty=1 orphan=4 prunable=0\n"
                "agent-hub checkpoints:0 dirty:0 orphan:0 prunable:0\n"
                "portfolio-ai checkpoints:3 dirty:0 orphan:3 prunable:0\n"
                "monkey-fight checkpoints:1 dirty:1 orphan:1 prunable:0"
            ),
        ])
        result = await manage_tasks(mock_bash, action="cleanup_all_safe")

        assert "CLEANUP[all]:repos=5 needs_cleanup=5 checkpoints=6 dirty=0 orphan=18 prunable=4" in result
        assert "Pruned merged orphan task branches: 4" in result
        assert "Pruned closed orphan task branches: 10" in result
        assert "CLEANUP[all]:repos=5 needs_cleanup=2 checkpoints=4 dirty=1 orphan=4 prunable=0" in result
        mock_bash.assert_has_awaits([
            call("st cleanup status --all"),
            call("st cleanup checkpoints --auto --all"),
            call("st cleanup status --all"),
        ])

    @pytest.mark.asyncio
    async def test_resolve_conflict_reopens_and_dispatches(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            return_value='{"task_id":"task-42","status":"dispatched_for_conflict_resolution"}'
        )
        result = await manage_tasks(
            mock_bash,
            action="resolve_conflict",
            task_id="task-42",
            project_id="summitflow",
        )

        assert "dispatched_for_conflict_resolution" in result
        mock_bash.assert_awaited_once_with("st -P summitflow git resolve-conflict task-42")

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
    async def test_done_falls_back_to_retire_lane_cleanup_for_retired_noop_lane(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                (
                    "ERROR Diff gate blocked completion: No files changed vs base branch — "
                    "task has no code changes\n"
                ),
                "Deleted 1 checkpoint residue",
            ]
        )
        mock_db = AsyncMock()
        completed = MagicMock(
            status="completed",
            current_branch="task-42/main",
            created_at=datetime.now(UTC),
            workstream_status="retired",
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
                mock_bash, action="done", task_id="task-42", project_id="summitflow"
            )

        assert "Fallback: Retired 1 session-backed checkpoint record(s) for task-42" in result
        assert "Checkpoint cleanup: Deleted 1 checkpoint residue" in result
        assert mock_bash.await_args_list[0].args[0] == "st -P summitflow done task-42"
        assert mock_bash.await_args_list[1].args[0] == "st -P summitflow cleanup checkpoints --auto"

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

        mock_bash = AsyncMock(
            side_effect=[
                "",
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
        assert mock_bash.await_args_list[0].args[0] == "st -P summitflow exec-log task-42 -n 40 --debug"
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --message 'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )

    @pytest.mark.asyncio
    async def test_reconcile_stops_when_checkpoint_is_missing(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "",
                "ERROR No checkpoint found for task-42. Was it claimed?\n",
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

        assert "Reconcile stopped for task-42" in result
        assert "direct task context" in result
        assert "Do not admin-close it from session evidence" in result
        assert mock_bash.await_count == 2
        assert mock_bash.await_args_list[0].args[0] == (
            "st -P summitflow exec-log task-42 -n 40 --debug"
        )
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )

    @pytest.mark.asyncio
    async def test_reconcile_stops_when_checkpoint_is_dirty(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "",
                "Claimed checkpoint has uncommitted changes.\n  Path: /tmp/repo\n  Smart mode could not create a clean checkpoint.",
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

        assert "Reconcile stopped for task-42" in result
        assert "direct task context" in result
        assert "Do not admin-close it from session evidence" in result
        assert mock_bash.await_count == 2
        assert mock_bash.await_args_list[0].args[0] == (
            "st -P summitflow exec-log task-42 -n 40 --debug"
        )
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )

    @pytest.mark.asyncio
    async def test_reconcile_stops_when_task_is_not_ready(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "",
                "ERROR Task not ready to complete: subtasks, steps\n",
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

        assert "Reconcile stopped for task-42" in result
        assert "not ready to complete" in result
        assert "Do not admin-close it from session evidence" in result
        assert mock_bash.await_count == 2
        assert mock_bash.await_args_list[0].args[0] == "st -P summitflow exec-log task-42 -n 40 --debug"
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )

    @pytest.mark.asyncio
    async def test_reconcile_retires_noop_lane_when_diff_gate_reports_no_code_changes(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "",
                (
                    "PASS Main checkout dirty, stashing changes before finalization...\n"
                    "ERROR Diff gate blocked completion: No files changed vs base branch — "
                    "task has no code changes\n"
                    "  Use --skip-diff-gate for non-code tasks (docs, config).\n"
                ),
                "Deleted 1 checkpoint residue",
            ]
        )
        mock_db = AsyncMock()
        completed_session = MagicMock(
            status="completed",
            summary_oneliner="No-op completion candidate",
            created_at=datetime.now(UTC),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [completed_session]
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

        assert "Reconcile retired no-op task residue for task-42" in result
        assert "task was left open" in result
        assert "Checkpoint cleanup: Deleted 1 checkpoint residue" in result
        assert completed_session.workstream_status == "retired"
        assert "diff gate reported no code changes" in completed_session.workstream_note
        assert mock_bash.await_count == 3
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --message "
            "'Reconciled from Agent Hub session evidence: No-op completion candidate'"
        )
        assert mock_bash.await_args_list[2].args[0] == "st -P summitflow cleanup checkpoints --auto"

    @pytest.mark.asyncio
    async def test_reconcile_reports_cleanup_empty_output(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "",
                (
                    "PASS Main checkout dirty, stashing changes before finalization...\n"
                    "ERROR Diff gate blocked completion: No files changed vs base branch — "
                    "task has no code changes\n"
                ),
                "",
            ]
        )
        mock_db = AsyncMock()
        completed_session = MagicMock(
            status="completed",
            summary_oneliner="No-op completion candidate",
            created_at=datetime.now(UTC),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [completed_session]
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

        assert "Checkpoint cleanup returned no output for task-42." in result
        assert mock_bash.await_count == 3
        assert mock_bash.await_args_list[2].args[0] == "st -P summitflow cleanup checkpoints --auto"

    @pytest.mark.asyncio
    async def test_reconcile_stops_when_recent_execution_activity_is_present(self):
        from app.services.tools._executor_io import manage_tasks

        recent_line = (
            f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}|INFO|Starting autonomous execution"
        )
        mock_bash = AsyncMock(side_effect=[f"{recent_line}\n"])
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

        assert "Reconcile stopped for task-42" in result
        assert "recent autonomous activity" in result
        assert mock_bash.await_count == 1
        assert mock_bash.await_args_list[0].args[0] == (
            "st -P summitflow exec-log task-42 -n 40 --debug"
        )

    @pytest.mark.asyncio
    async def test_reconcile_stops_missing_checkpoint_before_cleanup(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "",
                "ERROR No checkpoint found for task-42. Was it claimed?\n",
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

        assert "Reconcile stopped for task-42" in result
        assert "direct task context" in result
        assert mock_bash.await_count == 2
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )

    @pytest.mark.asyncio
    async def test_reconcile_admin_closes_after_status_update_failure_recovery_hint(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "",
                (
                    "PASS Task task-42 completed. Checkpoint removed.\n"
                    "WARN Work published but status update failed: "
                    "{\"error\":\"http_error\",\"message\":\"Invalid transition from 'pending' to 'completed'.\"}\n"
                    "  Recovery: st done task-42 --admin\n"
                ),
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
            "st -P summitflow exec-log task-42 -n 40 --debug"
        )
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )
        assert mock_bash.await_args_list[2].args[0] == (
            "st -P summitflow done task-42 --admin --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )

    @pytest.mark.asyncio
    async def test_reconcile_cleans_terminal_merge_residue(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "",
                "Error: Cannot merge - task task-42 is already completed",
                "TASK:task-42|completed|P2|refactor|SIMPLE",
                "Deleted 1 checkpoint residue",
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

        assert "Cannot merge - task task-42 is already completed" in result
        assert "Checkpoint cleanup: Deleted 1 checkpoint residue" in result
        assert mock_bash.await_args_list[0].args[0] == "st -P summitflow exec-log task-42 -n 40 --debug"

    @pytest.mark.asyncio
    async def test_reconcile_finalizes_after_completed_without_checkpoint_merge(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "",
                "Task task-42 completed without checkpoint merge.",
                "TASK:task-42|completed|P2|refactor|SIMPLE",
                "Deleted 1 checkpoint residue",
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

        assert "Task task-42 completed without checkpoint merge." in result
        assert "Checkpoint cleanup: Deleted 1 checkpoint residue" in result
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )
        assert mock_bash.await_args_list[2].args[0] == "st -P summitflow context task-42 --compact"
        assert mock_bash.await_args_list[3].args[0] == "st -P summitflow cleanup checkpoints --auto"

    @pytest.mark.asyncio
    async def test_reconcile_treats_no_checkpoint_cleanup_as_already_closed(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "",
                "Error: Cannot merge - task task-42 is already completed",
                "TASK:task-42|completed|P2|refactor|SIMPLE",
                '{"task_id":"task-42","status":"skipped","reason":"no_checkpoint"}',
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

        assert "Cannot merge - task task-42 is already completed" in result
        assert '"reason":"no_checkpoint"' in result
        assert mock_bash.await_args_list[0].args[0] == (
            "st -P summitflow exec-log task-42 -n 40 --debug"
        )
        assert mock_bash.await_args_list[1].args[0] == (
            "st -P summitflow done task-42 --message "
            "'Reconciled from Agent Hub session evidence: Fixed the regression'"
        )
        assert mock_bash.await_args_list[2].args[0] == "st -P summitflow context task-42 --compact"
        assert mock_bash.await_args_list[3].args[0] == "st -P summitflow cleanup checkpoints --auto"

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
                "CHECKPOINT:task-42|main|/tmp/checkout/task-42",
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
    async def test_reconcile_blocked_without_completed_sessions_points_back_to_queue_state(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(return_value="TASK:task-42|blocked|P2|task|SIMPLE")
        mock_db = AsyncMock()
        blocked_session = MagicMock(
            status="blocked",
            current_branch="task-42/main",
            created_at=datetime.now(UTC) - timedelta(minutes=5),
            updated_at=datetime.now(UTC) - timedelta(minutes=5),
            workstream_status=None,
            workstream_note=None,
            workstream_updated_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [blocked_session]
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

        assert "Reconcile skipped for task-42: no completed sessions to justify closure" in result
        assert "Treat this as queue/checkpoint state, not closure residue." in result
        assert "Use `st context`, `st sessions`, and `st pulse` to keep the project moving." in result
        mock_bash.assert_awaited_once_with("st -P summitflow context task-42 --compact")

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
                "",
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
                "",
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

        mock_bash = AsyncMock(
            side_effect=[
                "Deleted 1 checkpoint residue",
            ]
        )
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

        assert "Retired 1 session-backed checkpoint record(s) for task-77" in result
        assert "Checkpoint cleanup: Deleted 1 checkpoint residue" in result
        assert completed.workstream_status == "retired"
        assert "Retired via task lane retire action" in completed.workstream_note
        assert mock_bash.await_args_list[0].args[0] == "st -P summitflow cleanup checkpoints --auto"

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

        mock_bash = AsyncMock(
            side_effect=[
                "TASK:task-77|completed|P2|task|SIMPLE",
                "Deleted 1 checkpoint residue",
            ]
        )
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

        assert "Retired 1 session-backed checkpoint record(s) for task-77" in result
        assert "Checkpoint cleanup: Deleted 1 checkpoint residue" in result
        assert active.status == "completed"
        assert active.workstream_status == "retired"
        assert "stale active" in active.workstream_note
        assert mock_bash.await_args_list[0].args[0] == "st -P summitflow context task-77 --compact"
        assert mock_bash.await_args_list[1].args[0] == "st -P summitflow cleanup checkpoints --auto"

    @pytest.mark.asyncio
    async def test_retire_lane_allows_stale_active_by_inactivity_while_task_is_running(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock(
            side_effect=[
                "TASK:task-77|running|P2|task|SIMPLE",
                "Deleted 1 checkpoint residue",
            ]
        )
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

        assert "Retired 1 session-backed checkpoint record(s) for task-77" in result
        assert "Checkpoint cleanup: Deleted 1 checkpoint residue" in result
        assert active.status == "completed"
        assert active.workstream_status == "retired"
        assert "Retired stale active session during retire_lane after" in active.workstream_note
        assert mock_bash.await_args_list[0].args[0] == "st -P summitflow context task-77 --compact"
        assert mock_bash.await_args_list[1].args[0] == "st -P summitflow cleanup checkpoints --auto"

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        from app.services.tools._executor_io import manage_tasks

        mock_bash = AsyncMock()
        result = await manage_tasks(mock_bash, action="nonsense")
        assert "Error" in result
        assert "Unknown action" in result


class TestManageBackups:
    """Tests for manage_backups tool."""

    @pytest.mark.asyncio
    @patch(
        "app.services.tools._executor_backups.fetch_backup_schedule_line",
        new_callable=AsyncMock,
        return_value="agent-hub            project    enabled  daily    30   Agent Hub",
    )
    @patch(
        "app.services.tools._executor_backups.fetch_latest_backup_status_line",
        new_callable=AsyncMock,
        return_value="LATEST bkp-123|completed|8.5MB",
    )
    async def test_protection_status_for_project(
        self,
        mock_status: AsyncMock,
        mock_schedule: AsyncMock,
    ):
        from app.services.tools._executor_backups import manage_backups

        mock_bash = AsyncMock()

        result = await manage_backups(
            mock_bash,
            action="protection_status",
            project_id="agent-hub",
        )

        assert "LATEST bkp-123|completed|8.5MB" in result
        assert "agent-hub            project    enabled  daily    30   Agent Hub" in result
        assert "---" in result
        mock_bash.assert_not_awaited()
        mock_status.assert_awaited_once_with("agent-hub")
        mock_schedule.assert_awaited_once_with("agent-hub")

    @pytest.mark.asyncio
    async def test_create_project_backup(self):
        from app.services.tools._executor_backups import manage_backups

        mock_bash = AsyncMock(return_value="QUEUED backup-task-1")
        result = await manage_backups(
            mock_bash,
            action="create",
            project_id="agent-hub",
            note="Pre-risk cleanup",
        )

        assert "QUEUED" in result
        mock_bash.assert_awaited_once_with("st -P agent-hub backup create -n 'Pre-risk cleanup'")

    @pytest.mark.asyncio
    async def test_restore_requires_backup_id(self):
        from app.services.tools._executor_backups import manage_backups

        mock_bash = AsyncMock()
        result = await manage_backups(mock_bash, action="restore", project_id="agent-hub")

        assert "backup_id required" in result
        mock_bash.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_schedule_requires_source_id(self):
        from app.services.tools._executor_backups import manage_backups

        mock_bash = AsyncMock()
        result = await manage_backups(mock_bash, action="schedule")

        assert "source_id required" in result
        mock_bash.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_restore_dry_run_uses_source(self):
        from app.services.tools._executor_backups import manage_backups

        mock_bash = AsyncMock(return_value="DRY_RUN task-restore-1")
        result = await manage_backups(
            mock_bash,
            action="restore",
            source_id=".claude",
            backup_id="bkp-123",
            dry_run=True,
        )

        assert "DRY_RUN" in result
        mock_bash.assert_awaited_once_with(
            "st backup restore bkp-123 --dry-run --source .claude"
        )
