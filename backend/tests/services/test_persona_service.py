"""Tests for persona_service.py — singleton fetch, context building, and creation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.persona import Persona
from app.services.persona_service import (
    _build_onboarding_bootstrap,
    _build_onboarding_continuation,
    get_or_create_persona,
    get_persona,
    get_persona_context_for_agent,
    get_persona_for_agent,
    get_persona_limit,
    get_persona_personality_for_agent,
    should_reset_persona_session,
    submit_and_review_onboarding,
)
from tests.conftest import create_mock_db_session


def _make_persona(**overrides) -> MagicMock:
    """Create a mock Persona with sensible defaults for testing."""
    defaults = {
        "id": 1,
        "agent_id": 10,
        "name": "Jenny",
        "personality": "I am a helpful assistant.",
        "heartbeat_instructions": "Check system health.",
        "user_context": "User prefers concise answers.",
        "voice_id": "en-US-AriaNeural",
        "voice_enabled": False,
        "heartbeat_interval_minutes": 60,
        "avatar_url": None,
        "greeting": "Hello!",
        "onboarding_complete": True,
        "onboarding_phase": "complete",
        "onboarding_attempts": 0,
        "session_reset_mode": "off",
        "session_reset_hour": 9,
        "session_reset_idle_minutes": 120,
        "limits": None,
        "version": 3,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Persona)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock



class TestGetPersona:
    """Tests for get_persona() — singleton fetch."""

    @pytest.mark.asyncio
    async def test_returns_persona_when_exists(self):
        persona = _make_persona()
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        result = await get_persona(db)

        assert result is persona
        assert result.name == "Jenny"

    @pytest.mark.asyncio
    async def test_returns_none_when_empty(self):
        db = create_mock_db_session()

        result = await get_persona(db)

        assert result is None


class _ExplodingSession:
    def __init__(self, session_id: str):
        self.id = session_id
        self.__dict__["id"] = session_id

    @property
    def updated_at(self):  # pragma: no cover - the test ensures this is never used
        raise AssertionError("updated_at property should not be accessed directly")


class TestGetPersonaForAgent:
    """Tests for get_persona_for_agent() — match by agent_id."""

    @pytest.mark.asyncio
    async def test_returns_persona_matching_agent(self):
        persona = _make_persona(agent_id=42)
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        result = await get_persona_for_agent(db, agent_id=42)

        assert result is persona
        assert result.agent_id == 42

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self):
        db = create_mock_db_session()

        result = await get_persona_for_agent(db, agent_id=999)

        assert result is None


class TestShouldResetPersonaSession:
    @pytest.mark.asyncio
    async def test_uses_explicit_query_when_updated_at_not_loaded(self):
        persona = _make_persona(
            session_reset_mode="idle",
            session_reset_idle_minutes=5,
        )
        db = create_mock_db_session()
        persona_result = MagicMock()
        persona_result.scalar_one_or_none.return_value = persona
        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = datetime.now(UTC) - timedelta(minutes=10)
        db.execute.side_effect = [persona_result, session_result]

        should_reset = await should_reset_persona_session(db, _ExplodingSession("sess-1"))

        assert should_reset is True


class TestGetPersonaPersonalityForAgent:
    """Tests for get_persona_personality_for_agent()."""

    @pytest.mark.asyncio
    async def test_returns_personality_text(self):
        persona = _make_persona(personality="I'm a creative coder.")
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        result = await get_persona_personality_for_agent(db, agent_id=10)

        assert result == "I'm a creative coder."

    @pytest.mark.asyncio
    async def test_returns_none_when_no_persona(self):
        db = create_mock_db_session()

        result = await get_persona_personality_for_agent(db, agent_id=999)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_personality_is_null(self):
        persona = _make_persona(personality=None)
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        result = await get_persona_personality_for_agent(db, agent_id=10)

        assert result is None


class TestOnboardingBootstrapTemplates:
    """Tests for the onboarding bootstrap template functions."""

    def test_bootstrap_includes_persona_name(self):
        result = _build_onboarding_bootstrap("Jenny", has_prior_context=False)
        assert "Jenny" in result
        assert "Structured Onboarding" in result

    def test_bootstrap_includes_all_10_topics(self):
        result = _build_onboarding_bootstrap("Jenny", has_prior_context=False)
        for i in range(1, 11):
            assert f"{i}." in result

    def test_bootstrap_with_prior_context_adds_note(self):
        result = _build_onboarding_bootstrap("Jenny", has_prior_context=True)
        assert "Previous user context exists" in result
        assert "read_user_context" in result

    def test_bootstrap_without_prior_context_no_note(self):
        result = _build_onboarding_bootstrap("Jenny", has_prior_context=False)
        assert "Previous user context exists" not in result

    def test_bootstrap_mentions_submit_onboarding(self):
        result = _build_onboarding_bootstrap("Jenny", has_prior_context=False)
        assert "submit_onboarding" in result

    def test_continuation_includes_persona_name(self):
        result = _build_onboarding_continuation("Jenny")
        assert "Jenny" in result
        assert "Continuation" in result
        assert "read_user_context" in result

    def test_continuation_mentions_submit_onboarding(self):
        result = _build_onboarding_continuation("Jenny")
        assert "submit_onboarding" in result

    def test_custom_name_injected(self):
        result = _build_onboarding_bootstrap("Aria", has_prior_context=False)
        assert "Aria" in result
        assert "Jenny" not in result


class TestGetPersonaContextForAgent:
    """Tests for get_persona_context_for_agent() — core context injection."""

    @pytest.mark.asyncio
    async def test_identity_tag_always_present(self):
        persona = _make_persona(
            personality=None,
            heartbeat_instructions=None,
            user_context=None,
        )
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert result is not None
        assert '<identity name="Jenny" />' in result

    @pytest.mark.asyncio
    async def test_personality_section_present_when_set(self):
        persona = _make_persona(personality="I love coding.")
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<personality>" in result
        assert "I love coding." in result

    @pytest.mark.asyncio
    async def test_personality_section_absent_when_null(self):
        persona = _make_persona(personality=None)
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<personality>" not in result

    @pytest.mark.asyncio
    async def test_heartbeat_instructions_present_when_set(self):
        persona = _make_persona(heartbeat_instructions="Check task queue.")
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        with patch(
            "app.services.persona_instruction_service.get_persona_heartbeat_instructions",
            new_callable=AsyncMock,
            return_value="Check task queue.",
        ):
            result = await get_persona_context_for_agent(db, agent_id=10, task_type="heartbeat")

        assert "<heartbeat_instructions>" in result
        assert "Check task queue." in result

    @pytest.mark.asyncio
    async def test_heartbeat_instructions_absent_when_null(self):
        persona = _make_persona(heartbeat_instructions=None)
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<heartbeat_instructions>" not in result

    @pytest.mark.asyncio
    async def test_user_context_present_when_set(self):
        persona = _make_persona(user_context="Prefers dark mode.")
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<user_context>" in result
        assert "Prefers dark mode." in result

    @pytest.mark.asyncio
    async def test_evolution_guidelines_always_present(self):
        persona = _make_persona(
            personality=None,
            heartbeat_instructions=None,
            user_context=None,
        )
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<evolution_guidelines>" in result
        assert "Self-Evolution Guidelines" in result

    @pytest.mark.asyncio
    async def test_phase_not_started_injects_bootstrap_and_advances(self):
        """Phase not_started → inject bootstrap, advance to in_progress."""
        persona = _make_persona(
            onboarding_complete=False,
            onboarding_phase="not_started",
        )
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<onboarding>" in result
        assert "Structured Onboarding" in result
        assert persona.onboarding_phase == "in_progress"

    @pytest.mark.asyncio
    async def test_phase_in_progress_injects_continuation(self):
        """Phase in_progress → inject continuation prompt."""
        persona = _make_persona(
            onboarding_complete=False,
            onboarding_phase="in_progress",
        )
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<onboarding>" in result
        assert "Continuation" in result

    @pytest.mark.asyncio
    async def test_phase_pending_approval_injects_waiting_message(self):
        """Phase pending_approval → inject waiting message."""
        persona = _make_persona(
            onboarding_complete=False,
            onboarding_phase="pending_approval",
        )
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<onboarding>" in result
        assert "Under Review" in result

    @pytest.mark.asyncio
    async def test_phase_complete_no_onboarding_injection(self):
        """Phase complete → no onboarding block at all."""
        persona = _make_persona(
            onboarding_complete=True,
            onboarding_phase="complete",
        )
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "<onboarding>" not in result

    @pytest.mark.asyncio
    async def test_phase_not_started_with_prior_context(self):
        """Bootstrap should note prior context exists when user_context is set."""
        persona = _make_persona(
            onboarding_complete=False,
            onboarding_phase="not_started",
            user_context="Some prior context.",
        )
        db = create_mock_db_session()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result_persona

        result = await get_persona_context_for_agent(db, agent_id=10)

        assert "Previous user context exists" in result

    @pytest.mark.asyncio
    async def test_returns_none_when_no_persona(self):
        db = create_mock_db_session()

        result = await get_persona_context_for_agent(db, agent_id=999)

        assert result is None


class TestSubmitAndReviewOnboarding:
    """Tests for submit_and_review_onboarding() — dual-model approval gate."""

    @pytest.mark.asyncio
    async def test_both_approve_completes_onboarding(self):
        persona = _make_persona(
            onboarding_phase="in_progress",
            onboarding_complete=False,
        )
        db = create_mock_db_session()
        # get_persona returns our mock
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        # Mock complete_internal to return APPROVED from both reviewers
        mock_result_obj = MagicMock()
        mock_result_obj.content = "APPROVED\n\nEverything looks great."

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                return_value=mock_result_obj,
            ),
        ):
            result = await submit_and_review_onboarding(db, "Full summary", "Context snapshot")

        assert result["status"] == "approved"
        assert persona.onboarding_phase == "complete"
        assert persona.onboarding_complete is True

    @pytest.mark.asyncio
    async def test_one_rejects_sends_back(self):
        persona = _make_persona(
            onboarding_phase="in_progress",
            onboarding_complete=False,
        )
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        # First reviewer approves, second rejects
        approved_result = MagicMock()
        approved_result.content = "APPROVED\n\nLooks good."
        rejected_result = MagicMock()
        rejected_result.content = "REJECTED\n\nMissing schedule info."

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                side_effect=[approved_result, rejected_result],
            ),
        ):
            result = await submit_and_review_onboarding(db, "Partial summary", None)

        assert result["status"] == "rejected"
        assert persona.onboarding_phase == "in_progress"
        assert persona.onboarding_complete is False

    @pytest.mark.asyncio
    async def test_sets_pending_approval_before_review(self):
        persona = _make_persona(
            onboarding_phase="in_progress",
            onboarding_complete=False,
        )
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        mock_result_obj = MagicMock()
        mock_result_obj.content = "APPROVED\n\nAll good."

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        phases_seen: list[str] = []

        original_commit = db.commit

        async def track_commit():
            phases_seen.append(persona.onboarding_phase)
            return await original_commit()

        db.commit = track_commit

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                return_value=mock_result_obj,
            ),
        ):
            await submit_and_review_onboarding(db, "Summary", None)

        # First commit should be pending_approval, second should be complete
        assert "pending_approval" in phases_seen


    @pytest.mark.asyncio
    async def test_reviewer_system_error_returns_error_status(self):
        """When reviewers fail due to system errors (not rejection), status is 'error'."""
        persona = _make_persona(
            onboarding_phase="in_progress",
            onboarding_complete=False,
        )
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        # Both reviewers fail with system errors (exhausted retries)
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                side_effect=ConnectionError("model unreachable"),
            ),
            patch("app.services._persona_templates.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await submit_and_review_onboarding(db, "Summary", None)

        assert result["status"] == "error"
        assert persona.onboarding_phase == "in_progress"
        assert "Review failed after" in result["feedback"]


class TestGetOrCreatePersona:
    """Tests for get_or_create_persona() — singleton creation."""

    @pytest.mark.asyncio
    async def test_returns_existing_persona(self):
        persona = _make_persona()
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        result = await get_or_create_persona(db)

        assert result is persona

    @pytest.mark.asyncio
    async def test_creates_default_when_missing(self):
        db = create_mock_db_session()

        mock_agent = MagicMock()
        mock_agent.id = 10
        mock_agent.name = "Jenny"
        mock_agent.slug = "persona"

        with patch("app.services.agent_service.get_agent_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_agent)
            mock_get_svc.return_value = mock_svc

            result = await get_or_create_persona(db)

            assert isinstance(result, Persona)
            assert result.agent_id == 10
            db.add.assert_called_once()
            db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_when_no_agent(self):
        db = create_mock_db_session()

        with patch("app.services.agent_service.get_agent_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=None)
            mock_get_svc.return_value = mock_svc

            with pytest.raises(RuntimeError, match="Persona agent not found"):
                await get_or_create_persona(db)


class TestSessionAutoReset:
    """Tests for should_reset_persona_session()."""

    @pytest.mark.asyncio
    async def test_off_mode_never_resets(self):
        persona = _make_persona(session_reset_mode="off")
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        session = MagicMock()
        session.updated_at = datetime.now(UTC) - timedelta(days=5)

        result = await should_reset_persona_session(db, session)
        assert result is False

    @pytest.mark.asyncio
    async def test_daily_resets_stale_session(self):
        """Daily mode resets sessions from before today's reset hour."""
        persona = _make_persona(session_reset_mode="daily", session_reset_hour=9)
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        # Session from yesterday
        session = MagicMock()
        session.updated_at = datetime.now(UTC) - timedelta(days=1)

        result = await should_reset_persona_session(db, session)
        assert result is True

    @pytest.mark.asyncio
    async def test_daily_keeps_recent_session(self):
        """Daily mode keeps sessions from after today's reset hour."""
        persona = _make_persona(session_reset_mode="daily", session_reset_hour=0)
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        # Session from just now
        session = MagicMock()
        session.updated_at = datetime.now(UTC)

        result = await should_reset_persona_session(db, session)
        assert result is False

    @pytest.mark.asyncio
    async def test_idle_resets_stale_session(self):
        """Idle mode resets sessions idle longer than threshold."""
        persona = _make_persona(
            session_reset_mode="idle", session_reset_idle_minutes=30,
        )
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        # Session idle for 60 minutes
        session = MagicMock()
        session.updated_at = datetime.now(UTC) - timedelta(minutes=60)

        result = await should_reset_persona_session(db, session)
        assert result is True

    @pytest.mark.asyncio
    async def test_idle_keeps_active_session(self):
        """Idle mode keeps sessions that are still active."""
        persona = _make_persona(
            session_reset_mode="idle", session_reset_idle_minutes=120,
        )
        db = create_mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = persona
        db.execute.return_value = mock_result

        # Session updated 10 minutes ago
        session = MagicMock()
        session.updated_at = datetime.now(UTC) - timedelta(minutes=10)

        result = await should_reset_persona_session(db, session)
        assert result is False

    @pytest.mark.asyncio
    async def test_no_persona_returns_false(self):
        db = create_mock_db_session()
        session = MagicMock()
        session.updated_at = datetime.now(UTC)

        result = await should_reset_persona_session(db, session)
        assert result is False


class TestGetPersonaLimit:
    """Tests for get_persona_limit() — configurable limits."""

    def test_returns_default_when_no_limits(self):
        persona = _make_persona(limits=None)
        assert get_persona_limit(persona, "max_turns") == 200

    def test_returns_custom_limit(self):
        persona = _make_persona(limits={"max_turns": 500})
        assert get_persona_limit(persona, "max_turns") == 500

    def test_returns_default_for_unknown_key(self):
        persona = _make_persona(limits={"max_turns": 500})
        assert get_persona_limit(persona, "unknown_key") == 0

    def test_returns_default_when_persona_is_none(self):
        assert get_persona_limit(None, "max_turns") == 200
